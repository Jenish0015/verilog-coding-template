`timescale 1ns/1ps

// =============================================================================
// AXI-Lite Slave — Register Map
// =============================================================================
//
//  0x00  CTRL        (RW)
//          [0]   start     — write 1 to launch pipeline (self-clearing)
//          [1]   acc_en    — STICKY: accumulate mode persists until cleared
//          [2]   irq_en    — enable IRQ output
//          [7:3] reserved  — RAZ/WI
//
//  0x04  DATA_IN     (RW, double-buffered)
//          Writes go into a SHADOW register.
//          Shadow is transferred to the active DATA_IN only when the
//          pipeline is IDLE (not busy). If a write arrives while busy,
//          WREADY is deasserted until the pipeline finishes, then the
//          write completes. This prevents mid-pipeline data corruption.
//
//  0x08  DATA_OUT    (RO)
//          Normal mode  (acc_en=0): DATA_OUT  = result
//          Accumulate   (acc_en=1): DATA_OUT += result  (SATURATING at 0xFFFFFFFF)
//
//  0x0C  STATUS      (RO, read-to-clear bit[0])
//          [0]   done   — set when pipeline completes; CLEARED ON READ
//          [1]   busy   — high while 4-cycle pipeline is in flight
//          [2]   ovf    — set if saturating add overflowed; CLEARED ON READ
//
//  0x10  SCRATCH     (RW) — byte-strobe, no side-effects
//
//  0x14  IRQ_STATUS  (RO, read-to-clear bit[0])
//          [0]   irq_done — latches when done & irq_en=1; CLEARED ON READ
//
//  0x18  TRIGGER_CNT (RO) — counts number of times CTRL[0] has been written;
//                           reset to 0 by writing 1 to CTRL[3] (reserved bit
//                           repurposed as clear-counter strobe)
//
// Unmapped: read → RDATA=0 RRESP=SLVERR; write → ignored BRESP=SLVERR
//
// Pipeline (4 stages):
//   S1: xor_val  = DATA_IN ^ 32'hA5A5A5A5
//   S2: sum_val  = {1'b0,xor_val} + {1'b0,DATA_IN}   (33-bit)
//   S3: shift    = sum_val[32:0] >> 2
//   S4: result   = shift ^ SCRATCH[15:0]              (scratch-XOR finaliser)
//
// Saturating accumulator (acc_en=1):
//   temp = {1'b0,DATA_OUT} + {1'b0,result}
//   DATA_OUT = temp[32] ? 32'hFFFF_FFFF : temp[31:0]
//   STATUS[2] (ovf) set if temp[32]=1
//
// IRQ pin = registered (ctrl_irq_en & irq_status[0])
//
// =============================================================================

module axi_lite_slave #(
    parameter DATA_WIDTH = 32,
    parameter ADDR_WIDTH = 6
)(
    input  logic                   ACLK,
    input  logic                   ARESETn,

    input  logic [ADDR_WIDTH-1:0]  AWADDR,
    input  logic                   AWVALID,
    output logic                   AWREADY,

    input  logic [DATA_WIDTH-1:0]  WDATA,
    input  logic [3:0]             WSTRB,
    input  logic                   WVALID,
    output logic                   WREADY,

    output logic [1:0]             BRESP,
    output logic                   BVALID,
    input  logic                   BREADY,

    input  logic [ADDR_WIDTH-1:0]  ARADDR,
    input  logic                   ARVALID,
    output logic                   ARREADY,

    output logic [DATA_WIDTH-1:0]  RDATA,
    output logic [1:0]             RRESP,
    output logic                   RVALID,
    input  logic                   RREADY,

    output logic                   IRQ
);

    // -------------------------------------------------------------------------
    // Address map
    // -------------------------------------------------------------------------
    localparam [ADDR_WIDTH-1:0] ADDR_CTRL        = 6'h00;
    localparam [ADDR_WIDTH-1:0] ADDR_DATA_IN     = 6'h04;
    localparam [ADDR_WIDTH-1:0] ADDR_DATA_OUT    = 6'h08;
    localparam [ADDR_WIDTH-1:0] ADDR_STATUS      = 6'h0C;
    localparam [ADDR_WIDTH-1:0] ADDR_SCRATCH     = 6'h10;
    localparam [ADDR_WIDTH-1:0] ADDR_IRQ_STATUS  = 6'h14;
    localparam [ADDR_WIDTH-1:0] ADDR_TRIGGER_CNT = 6'h18;

    localparam [1:0] RESP_OKAY   = 2'b00;
    localparam [1:0] RESP_SLVERR = 2'b10;

    // -------------------------------------------------------------------------
    // Registers
    // -------------------------------------------------------------------------
    logic [DATA_WIDTH-1:0] reg_ctrl;
    logic [DATA_WIDTH-1:0] reg_data_in;       // active (pipeline reads this)
    logic [DATA_WIDTH-1:0] reg_data_in_shadow;// CPU writes go here first
    logic [DATA_WIDTH-1:0] reg_data_out;
    logic [DATA_WIDTH-1:0] reg_status;        // [2:0] used
    logic [DATA_WIDTH-1:0] reg_scratch;
    logic [DATA_WIDTH-1:0] reg_irq_status;
    logic [DATA_WIDTH-1:0] reg_trigger_cnt;

    // CTRL aliases
    logic ctrl_start;
    logic ctrl_acc_en;
    logic ctrl_irq_en;
    logic ctrl_cnt_clr;   // CTRL[3] — clear trigger counter
    assign ctrl_start   = reg_ctrl[0];
    assign ctrl_acc_en  = reg_ctrl[1];
    assign ctrl_irq_en  = reg_ctrl[2];
    assign ctrl_cnt_clr = reg_ctrl[3];

    // -------------------------------------------------------------------------
    // 4-stage pipeline
    // -------------------------------------------------------------------------
    logic        pipe_v  [0:3];   // valid per stage
    logic [31:0] pipe_din[0:3];   // captured DATA_IN
    logic [31:0] pipe_scr[0:3];   // captured SCRATCH at trigger time

    logic [31:0] pipe_xor [1:3];
    logic [32:0] pipe_sum [2:3];
    logic [31:0] pipe_shft[3:3];

    logic pipeline_busy;
    assign pipeline_busy = pipe_v[0] | pipe_v[1] | pipe_v[2] | pipe_v[3];

    // Shadow → active transfer: happens when pipeline goes idle
    // (i.e. was busy last cycle, now idle, AND there is a pending shadow write)
    logic shadow_pending;
    logic pipeline_busy_q;

    always_ff @(posedge ACLK or negedge ARESETn) begin
        if (!ARESETn)
            pipeline_busy_q <= 1'b0;
        else
            pipeline_busy_q <= pipeline_busy;
    end

    // falling edge of busy = pipeline just finished
    logic pipe_done_pulse;
    assign pipe_done_pulse = pipeline_busy_q & ~pipeline_busy;

    always_ff @(posedge ACLK or negedge ARESETn) begin
        if (!ARESETn) begin
            pipe_v[0] <= 1'b0; pipe_v[1] <= 1'b0;
            pipe_v[2] <= 1'b0; pipe_v[3] <= 1'b0;
            pipe_din[0] <= '0; pipe_din[1] <= '0;
            pipe_din[2] <= '0; pipe_din[3] <= '0;
            pipe_scr[0] <= '0; pipe_scr[1] <= '0;
            pipe_scr[2] <= '0; pipe_scr[3] <= '0;
            pipe_xor[1] <= '0; pipe_xor[2] <= '0; pipe_xor[3] <= '0;
            pipe_sum[2]  <= '0; pipe_sum[3]  <= '0;
            pipe_shft[3] <= '0;
        end else begin
            // Stage 0 → 1
            pipe_v[1]   <= pipe_v[0];
            pipe_xor[1] <= pipe_din[0] ^ 32'hA5A5A5A5;
            pipe_din[1] <= pipe_din[0];
            pipe_scr[1] <= pipe_scr[0];

            // Stage 1 → 2
            pipe_v[2]   <= pipe_v[1];
            pipe_sum[2] <= {1'b0, pipe_xor[1]} + {1'b0, pipe_din[1]};
            pipe_din[2] <= pipe_din[1];
            pipe_scr[2] <= pipe_scr[1];

            // Stage 2 → 3
            pipe_v[3]    <= pipe_v[2];
            pipe_sum[3]  <= pipe_sum[2];
            pipe_shft[3] <= (pipe_sum[2] & 33'h1_FFFF_FFFF) >> 2;
            pipe_scr[3]  <= pipe_scr[2];

            // Stage 0 loaded by write-channel (see below)
            pipe_v[0] <= 1'b0; // default: cleared each cycle unless triggered
        end
    end

    // -------------------------------------------------------------------------
    // Pipeline completion — update DATA_OUT, STATUS, IRQ_STATUS
    // -------------------------------------------------------------------------
    always_ff @(posedge ACLK or negedge ARESETn) begin
        if (!ARESETn) begin
            reg_data_out   <= '0;
            reg_status     <= '0;
            reg_irq_status <= '0;
            IRQ            <= 1'b0;
        end else begin
            // Keep busy bit in sync
            reg_status[1] <= pipeline_busy;

            if (pipe_v[3]) begin
                // Final result: XOR with lower 16 bits of captured scratch
                logic [31:0] result;
                result = pipe_shft[3] ^ {16'b0, pipe_scr[3][15:0]};

                if (ctrl_acc_en) begin
                    // Saturating add
                    logic [32:0] acc_sum;
                    acc_sum = {1'b0, reg_data_out} + {1'b0, result};
                    if (acc_sum[32]) begin
                        reg_data_out  <= 32'hFFFF_FFFF;
                        reg_status[2] <= 1'b1;  // overflow flag
                    end else begin
                        reg_data_out  <= acc_sum[31:0];
                        reg_status[2] <= 1'b0;
                    end
                end else begin
                    reg_data_out  <= result;
                    reg_status[2] <= 1'b0;
                end

                reg_status[0]     <= 1'b1;        // done
                reg_irq_status[0] <= ctrl_irq_en;  // latch IRQ
            end

            // IRQ pin = flopped (irq_en & irq_status[0])
            IRQ <= ctrl_irq_en & reg_irq_status[0];
        end
    end

    // -------------------------------------------------------------------------
    // Write channel
    // DATA_IN writes are held (WREADY deasserted) while pipeline busy
    // -------------------------------------------------------------------------
    logic                  aw_latched;
    logic [ADDR_WIDTH-1:0] aw_addr;
    logic                  w_latched;
    logic [DATA_WIDTH-1:0] w_data;
    logic [3:0]            w_strb;

    // We need to know if a pending write is for DATA_IN so we can gate WREADY
    logic pending_data_in_write;
    assign pending_data_in_write = aw_latched && (aw_addr == ADDR_DATA_IN);

    always_ff @(posedge ACLK or negedge ARESETn) begin
        if (!ARESETn) begin
            AWREADY          <= 1'b0;
            WREADY           <= 1'b0;
            BVALID           <= 1'b0;
            BRESP            <= RESP_OKAY;
            aw_latched       <= 1'b0;
            w_latched        <= 1'b0;
            aw_addr          <= '0;
            w_data           <= '0;
            w_strb           <= '0;
            reg_ctrl         <= '0;
            reg_data_in      <= '0;
            reg_data_in_shadow <= '0;
            shadow_pending   <= 1'b0;
            reg_scratch      <= '0;
            reg_trigger_cnt  <= '0;
            pipe_v[0]        <= 1'b0;
            pipe_din[0]      <= '0;
            pipe_scr[0]      <= '0;
        end else begin

            // Default: pipeline stage 0 not triggered
            pipe_v[0] <= 1'b0;

            // Shadow → active transfer on pipeline-idle edge
            if (pipe_done_pulse && shadow_pending) begin
                reg_data_in    <= reg_data_in_shadow;
                shadow_pending <= 1'b0;
            end

            // Accept write address (always, even for DATA_IN)
            if (!aw_latched && !BVALID) begin
                AWREADY <= 1'b1;
                if (AWVALID) begin
                    aw_addr    <= AWADDR;
                    aw_latched <= 1'b1;
                    AWREADY    <= 1'b0;
                end
            end else begin
                AWREADY <= 1'b0;
            end

            // Accept write data
            // For DATA_IN: gate WREADY low while pipeline busy
            if (!w_latched && !BVALID) begin
                if (aw_latched && (aw_addr == ADDR_DATA_IN) && pipeline_busy) begin
                    // Hold WREADY low until pipeline finishes
                    WREADY <= 1'b0;
                end else begin
                    WREADY <= 1'b1;
                    if (WVALID) begin
                        w_data    <= WDATA;
                        w_strb    <= WSTRB;
                        w_latched <= 1'b1;
                        WREADY    <= 1'b0;
                    end
                end
            end else begin
                WREADY <= 1'b0;
            end

            // Commit write once both channels captured
            if (aw_latched && w_latched && !BVALID) begin
                case (aw_addr)
                    ADDR_CTRL: begin
                        if (w_strb[0]) begin
                            // [2:0] writable; [3] is cnt_clr strobe
                            reg_ctrl[2:0] <= w_data[2:0];
                            // Trigger
                            if (w_data[0] && !pipeline_busy) begin
                                pipe_v[0]   <= 1'b1;
                                pipe_din[0] <= reg_data_in;
                                pipe_scr[0] <= reg_scratch;
                                reg_ctrl[0] <= 1'b0;       // self-clear start
                                reg_status[0] <= 1'b0;     // clear done
                                reg_trigger_cnt <= reg_trigger_cnt + 1;
                            end
                            // Clear trigger counter
                            if (w_data[3])
                                reg_trigger_cnt <= '0;
                        end
                        BRESP <= RESP_OKAY;
                    end

                    ADDR_DATA_IN: begin
                        // Write goes to shadow; active updated when pipeline idle
                        if (w_strb[0]) reg_data_in_shadow[7:0]   <= w_data[7:0];
                        if (w_strb[1]) reg_data_in_shadow[15:8]  <= w_data[15:8];
                        if (w_strb[2]) reg_data_in_shadow[23:16] <= w_data[23:16];
                        if (w_strb[3]) reg_data_in_shadow[31:24] <= w_data[31:24];
                        if (!pipeline_busy) begin
                            // Immediately transfer to active if idle
                            if (w_strb[0]) reg_data_in[7:0]   <= w_data[7:0];
                            if (w_strb[1]) reg_data_in[15:8]  <= w_data[15:8];
                            if (w_strb[2]) reg_data_in[23:16] <= w_data[23:16];
                            if (w_strb[3]) reg_data_in[31:24] <= w_data[31:24];
                        end else begin
                            shadow_pending <= 1'b1;
                        end
                        BRESP <= RESP_OKAY;
                    end

                    ADDR_SCRATCH: begin
                        if (w_strb[0]) reg_scratch[7:0]   <= w_data[7:0];
                        if (w_strb[1]) reg_scratch[15:8]  <= w_data[15:8];
                        if (w_strb[2]) reg_scratch[23:16] <= w_data[23:16];
                        if (w_strb[3]) reg_scratch[31:24] <= w_data[31:24];
                        BRESP <= RESP_OKAY;
                    end

                    ADDR_DATA_OUT,
                    ADDR_STATUS,
                    ADDR_IRQ_STATUS,
                    ADDR_TRIGGER_CNT: begin
                        BRESP <= RESP_OKAY; // RO: ignore, OKAY
                    end

                    default: BRESP <= RESP_SLVERR;
                endcase

                BVALID     <= 1'b1;
                aw_latched <= 1'b0;
                w_latched  <= 1'b0;
            end

            if (BVALID && BREADY)
                BVALID <= 1'b0;

            // CTRL[3] auto-clears (cnt_clr strobe)
            if (reg_ctrl[3])
                reg_ctrl[3] <= 1'b0;
        end
    end

    // -------------------------------------------------------------------------
    // Read channel — STATUS[0], STATUS[2], IRQ_STATUS[0] are read-to-clear
    // DATA_IN reads return the SHADOW value (what CPU last wrote)
    // -------------------------------------------------------------------------
    typedef enum logic { RD_IDLE = 1'b0, RD_WAIT = 1'b1 } rd_state_t;
    rd_state_t rd_state;

    always_ff @(posedge ACLK or negedge ARESETn) begin
        if (!ARESETn) begin
            ARREADY  <= 1'b0;
            RVALID   <= 1'b0;
            RDATA    <= '0;
            RRESP    <= RESP_OKAY;
            rd_state <= RD_IDLE;
        end else begin
            case (rd_state)
                RD_IDLE: begin
                    ARREADY <= 1'b1;
                    if (ARVALID) begin
                        ARREADY <= 1'b0;
                        RVALID  <= 1'b1;
                        case (ARADDR)
                            ADDR_CTRL: begin
                                RDATA <= {28'b0, reg_ctrl[3:0]};
                                RRESP <= RESP_OKAY;
                            end
                            ADDR_DATA_IN: begin
                                // Returns shadow (what CPU wrote), not active
                                RDATA <= reg_data_in_shadow;
                                RRESP <= RESP_OKAY;
                            end
                            ADDR_DATA_OUT: begin
                                RDATA <= reg_data_out;
                                RRESP <= RESP_OKAY;
                            end
                            ADDR_STATUS: begin
                                RDATA         <= reg_status;
                                RRESP         <= RESP_OKAY;
                                reg_status[0] <= 1'b0;  // read-to-clear done
                                reg_status[2] <= 1'b0;  // read-to-clear ovf
                            end
                            ADDR_SCRATCH: begin
                                RDATA <= reg_scratch;
                                RRESP <= RESP_OKAY;
                            end
                            ADDR_IRQ_STATUS: begin
                                RDATA             <= reg_irq_status;
                                RRESP             <= RESP_OKAY;
                                reg_irq_status[0] <= 1'b0;
                            end
                            ADDR_TRIGGER_CNT: begin
                                RDATA <= reg_trigger_cnt;
                                RRESP <= RESP_OKAY;
                            end
                            default: begin
                                RDATA <= '0;
                                RRESP <= RESP_SLVERR;
                            end
                        endcase
                        rd_state <= RD_WAIT;
                    end
                end

                RD_WAIT: begin
                    ARREADY <= 1'b0;
                    if (RVALID && RREADY) begin
                        RVALID   <= 1'b0;
                        rd_state <= RD_IDLE;
                    end
                end

                default: rd_state <= RD_IDLE;
            endcase
        end
    end

endmodule