`timescale 1ns / 1ps

// Reference solution for axi_lite_slave (golden branch). Matches hidden cocotb tests.
module axi_lite_slave #(
    parameter DATA_WIDTH = 32,
    parameter ADDR_WIDTH = 6
)(
    input  wire                  ACLK,
    input  wire                  ARESETn,

    input  wire [ADDR_WIDTH-1:0]  AWADDR,
    input  wire                  AWVALID,
    output reg                   AWREADY,

    input  wire [DATA_WIDTH-1:0]  WDATA,
    input  wire [3:0]            WSTRB,
    input  wire                  WVALID,
    output reg                   WREADY,

    output reg  [1:0]            BRESP,
    output reg                   BVALID,
    input  wire                  BREADY,

    input  wire [ADDR_WIDTH-1:0]  ARADDR,
    input  wire                  ARVALID,
    output reg                   ARREADY,

    output reg [DATA_WIDTH-1:0]   RDATA,
    output reg [1:0]             RRESP,
    output reg                   RVALID,
    input  wire                  RREADY
);

    reg [31:0] ctrl_reg;
    reg [31:0] data_in_reg;
    reg [31:0] data_out_reg;
    reg [31:0] status_reg;
    reg        ctrl_prev;

    // Multi-cycle datapath: operand is latched on CTRL[0] rising edge; DATA_OUT updates
    // PIPE_LEN clocks later. Must match PIPE_CYC in hidden tests (test_axi_lite_slave_hidden.py).
    localparam [5:0] PIPE_LEN = 6'd32;
    reg [31:0] operand_reg;
    reg [5:0]  delay_cnt;

    localparam W_IDLE = 2'd0,
               W_DATA = 2'd1,
               W_RESP = 2'd2;

    reg [1:0] wstate;
    reg [ADDR_WIDTH-1:0] waddr;

    function [31:0] compute_transform;
        input [31:0] d;
        begin
            compute_transform = ((d ^ 32'hA5A5A5A5) + d) >> 2;
        end
    endfunction

    always @(posedge ACLK or negedge ARESETn) begin
        if (!ARESETn) begin
            wstate      <= W_IDLE;
            AWREADY     <= 1'b0;
            WREADY      <= 1'b0;
            BVALID      <= 1'b0;
            BRESP       <= 2'b00;
            waddr       <= '0;
            ctrl_reg    <= 32'b0;
            data_in_reg <= 32'b0;
        end else begin
            case (wstate)
                W_IDLE: begin
                    AWREADY <= 1'b1;
                    WREADY  <= 1'b0;
                    BVALID  <= 1'b0;
                    if (AWVALID && AWREADY) begin
                        waddr   <= AWADDR;
                        AWREADY <= 1'b0;
                        WREADY  <= 1'b1;
                        wstate  <= W_DATA;
                    end
                end
                W_DATA: begin
                    AWREADY <= 1'b0;
                    if (WVALID && WREADY) begin
                        WREADY <= 1'b0;
                        case (waddr)
                            6'h00: begin
                                if (WSTRB[0]) ctrl_reg[7:0]   <= WDATA[7:0];
                                if (WSTRB[1]) ctrl_reg[15:8]  <= WDATA[15:8];
                                if (WSTRB[2]) ctrl_reg[23:16] <= WDATA[23:16];
                                if (WSTRB[3]) ctrl_reg[31:24] <= WDATA[31:24];
                                BRESP  <= 2'b00;
                            end
                            6'h04: begin
                                if (WSTRB[0]) data_in_reg[7:0]   <= WDATA[7:0];
                                if (WSTRB[1]) data_in_reg[15:8]  <= WDATA[15:8];
                                if (WSTRB[2]) data_in_reg[23:16] <= WDATA[23:16];
                                if (WSTRB[3]) data_in_reg[31:24] <= WDATA[31:24];
                                BRESP  <= 2'b00;
                            end
                            default: BRESP <= 2'b10;
                        endcase
                        BVALID <= 1'b1;
                        wstate <= W_RESP;
                    end
                end
                W_RESP: begin
                    AWREADY <= 1'b0;
                    WREADY  <= 1'b0;
                    if (BVALID && BREADY) begin
                        BVALID  <= 1'b0;
                        AWREADY <= 1'b1;
                        wstate  <= W_IDLE;
                    end
                end
                default: wstate <= W_IDLE;
            endcase
        end
    end

    always @(posedge ACLK or negedge ARESETn) begin
        if (!ARESETn) begin
            ARREADY <= 1'b0;
            RVALID  <= 1'b0;
            RDATA   <= 32'b0;
            RRESP   <= 2'b00;
        end else begin
            if (!RVALID) begin
                ARREADY <= 1'b1;
                if (ARVALID && ARREADY) begin
                    ARREADY <= 1'b0;
                    case (ARADDR)
                        6'h00: begin
                            RDATA <= ctrl_reg;
                            RRESP <= 2'b00;
                        end
                        6'h04: begin
                            RDATA <= data_in_reg;
                            RRESP <= 2'b00;
                        end
                        6'h08: begin
                            RDATA <= data_out_reg;
                            RRESP <= 2'b00;
                        end
                        6'h0C: begin
                            RDATA <= status_reg;
                            RRESP <= 2'b00;
                        end
                        default: begin
                            RDATA <= 32'b0;
                            RRESP <= 2'b10;
                        end
                    endcase
                    RVALID <= 1'b1;
                end
            end else if (RREADY && RVALID) begin
                RVALID  <= 1'b0;
                ARREADY <= 1'b1;
            end
        end
    end

    always @(posedge ACLK or negedge ARESETn) begin
        if (!ARESETn) begin
            data_out_reg <= 32'b0;
            status_reg   <= 32'b0;
            ctrl_prev    <= 1'b0;
            operand_reg  <= 32'b0;
            delay_cnt    <= 6'd0;
        end else begin
            ctrl_prev <= ctrl_reg[0];
            if (ctrl_reg[0] && !ctrl_prev) begin
                operand_reg     <= data_in_reg;
                delay_cnt       <= PIPE_LEN;
                status_reg[0]   <= 1'b1;
            end else if (delay_cnt != 6'd0) begin
                if (delay_cnt == 6'd1)
                    data_out_reg <= compute_transform(operand_reg);
                delay_cnt <= delay_cnt - 6'd1;
            end
            if (!ctrl_reg[0])
                status_reg[0] <= 1'b0;
        end
    end

endmodule
