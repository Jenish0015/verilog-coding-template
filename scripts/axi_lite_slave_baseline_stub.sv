`timescale 1ns / 1ps

// Baseline: same ports as golden. Minimal AXI-Lite handshakes; no register map,
// no datapath, no decode errors. Hidden tests must fail on this file.
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

    localparam W_IDLE = 2'd0,
               W_DATA = 2'd1,
               W_RESP = 2'd2;

    reg [1:0] wstate;
    reg [ADDR_WIDTH-1:0] waddr;

    always @(posedge ACLK or negedge ARESETn) begin
        if (!ARESETn) begin
            wstate  <= W_IDLE;
            AWREADY <= 1'b0;
            WREADY  <= 1'b0;
            BVALID  <= 1'b0;
            BRESP   <= 2'b00;
            waddr   <= '0;
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
                    if (WVALID && WREADY) begin
                        WREADY <= 1'b0;
                        BRESP  <= 2'b00;
                        BVALID <= 1'b1;
                        wstate <= W_RESP;
                    end
                end
                W_RESP: begin
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
                    RRESP   <= 2'b00;
                    RDATA   <= 32'b0;
                    RVALID  <= 1'b1;
                end
            end else if (RREADY && RVALID) begin
                RVALID  <= 1'b0;
                ARREADY <= 1'b1;
            end
        end
    end

endmodule
