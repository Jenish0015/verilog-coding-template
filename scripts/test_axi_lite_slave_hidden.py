from __future__ import annotations
import os
from pathlib import Path
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge


async def axi_write(dut, addr, data, wstrb=0xF):
    dut.AWADDR.value = addr
    dut.AWVALID.value = 1
    dut.WVALID.value = 0
    dut.BREADY.value = 1
    for _ in range(50):
        await RisingEdge(dut.ACLK)
        if dut.AWREADY.value == 1:
            break
    dut.AWVALID.value = 0
    await RisingEdge(dut.ACLK)
    dut.WDATA.value = data
    dut.WSTRB.value = wstrb
    dut.WVALID.value = 1
    for _ in range(50):
        await RisingEdge(dut.ACLK)
        if dut.WREADY.value == 1:
            break
    dut.WVALID.value = 0
    await RisingEdge(dut.ACLK)
    for _ in range(50):
        await RisingEdge(dut.ACLK)
        if dut.BVALID.value == 1:
            break
    dut.BREADY.value = 0
    await RisingEdge(dut.ACLK)


async def axi_write_resp(dut, addr, data, wstrb=0xF):
    """AXI write that returns BRESP (for SLVERR checks)."""
    dut.AWADDR.value = addr
    dut.AWVALID.value = 1
    dut.WVALID.value = 0
    dut.BREADY.value = 1
    for _ in range(50):
        await RisingEdge(dut.ACLK)
        if dut.AWREADY.value == 1:
            break
    dut.AWVALID.value = 0
    await RisingEdge(dut.ACLK)

    dut.WDATA.value = data
    dut.WSTRB.value = wstrb
    dut.WVALID.value = 1
    for _ in range(50):
        await RisingEdge(dut.ACLK)
        if dut.WREADY.value == 1:
            break
    dut.WVALID.value = 0
    await RisingEdge(dut.ACLK)

    for _ in range(50):
        await RisingEdge(dut.ACLK)
        if dut.BVALID.value == 1:
            break

    bresp = dut.BRESP.value.integer
    dut.BREADY.value = 0
    await RisingEdge(dut.ACLK)
    return bresp


async def axi_read(dut, addr):
    data, _rresp = await axi_read_with_resp(dut, addr)
    return data


async def axi_read_with_resp(dut, addr):
    dut.ARADDR.value = addr
    dut.ARVALID.value = 1
    dut.RREADY.value = 1
    for _ in range(50):
        await RisingEdge(dut.ACLK)
        if dut.ARREADY.value == 1:
            break
    dut.ARVALID.value = 0
    data = 0
    rresp = 0
    for _ in range(50):
        if dut.RVALID.value == 1:
            data = dut.RDATA.value.integer
            rresp = dut.RRESP.value.integer
            break
        await RisingEdge(dut.ACLK)
    dut.RREADY.value = 0
    await RisingEdge(dut.ACLK)
    return data, rresp


async def reset_dut(dut):
    dut.ARESETn.value = 0
    dut.AWVALID.value = 0
    dut.WVALID.value = 0
    dut.BREADY.value = 0
    dut.ARVALID.value = 0
    dut.RREADY.value = 0
    dut.WSTRB.value = 0xF
    dut.AWADDR.value = 0
    dut.WDATA.value = 0
    dut.ARADDR.value = 0
    for _ in range(5):
        await RisingEdge(dut.ACLK)
    dut.ARESETn.value = 1
    for _ in range(3):
        await RisingEdge(dut.ACLK)


def compute_expected(val):
    return (((val ^ 0xA5A5A5A5) + val) & 0xFFFFFFFF) >> 2


# Must match PIPE_LEN in golden `sources/axi_lite_slave.sv` (multi-cycle datapath).
PIPE_CYC = 32


async def _wait_cycles(dut, cycles: int) -> None:
    for _ in range(cycles):
        await RisingEdge(dut.ACLK)


async def _wait_after_ctrl_pulse(dut) -> None:
    """Wait until pipelined DATA_OUT should be valid after a CTRL[0] rising edge."""
    await _wait_cycles(dut, PIPE_CYC + 12)


@cocotb.test()
async def test_axi_lite_write_read(dut):
    clock = Clock(dut.ACLK, 10, units="ns")
    clock.start(start_high=False)
    await reset_dut(dut)
    await axi_write(dut, 0x04, 5)
    await axi_write(dut, 0x00, 1)
    await _wait_after_ctrl_pulse(dut)
    result = await axi_read(dut, 0x08)
    expected = compute_expected(5)
    assert result == expected, f"DATA_OUT was {result}, expected {expected}"


@cocotb.test()
async def test_axi_lite_reset(dut):
    clock = Clock(dut.ACLK, 10, units="ns")
    clock.start(start_high=False)
    await reset_dut(dut)
    ctrl = await axi_read(dut, 0x00)
    assert ctrl == 0, f"CTRL reg should be 0 after reset, got {ctrl}"
    status = await axi_read(dut, 0x0C)
    assert status == 0, f"STATUS reg should be 0 after reset, got {status}"


@cocotb.test()
async def test_axi_lite_multiple_operations(dut):
    clock = Clock(dut.ACLK, 10, units="ns")
    clock.start(start_high=False)
    await reset_dut(dut)
    for input_val in [1, 15, 100, 255]:
        await axi_write(dut, 0x00, 0)
        for _ in range(5):
            await RisingEdge(dut.ACLK)
        await axi_write(dut, 0x04, input_val)
        await axi_write(dut, 0x00, 1)
        await _wait_after_ctrl_pulse(dut)
        result = await axi_read(dut, 0x08)
        expected = compute_expected(input_val)
        assert result == expected, f"For input {input_val}: got {result}, expected {expected}"


@cocotb.test()
async def test_axi_lite_back_to_back(dut):
    clock = Clock(dut.ACLK, 10, units="ns")
    clock.start(start_high=False)
    await reset_dut(dut)
    await axi_write(dut, 0x04, 7)
    await axi_write(dut, 0x00, 1)
    await _wait_after_ctrl_pulse(dut)
    result1 = await axi_read(dut, 0x08)
    expected1 = compute_expected(7)
    assert result1 == expected1, f"First op: got {result1}, expected {expected1}"
    await axi_write(dut, 0x00, 0)
    for _ in range(5):
        await RisingEdge(dut.ACLK)
    await axi_write(dut, 0x04, 20)
    await axi_write(dut, 0x00, 1)
    for _ in range(50):
        await RisingEdge(dut.ACLK)
    result2 = await axi_read(dut, 0x08)
    expected2 = compute_expected(20)
    assert result2 == expected2, f"Second op: got {result2}, expected {expected2}"
    await axi_write(dut, 0x00, 0)
    for _ in range(5):
        await RisingEdge(dut.ACLK)
    status = await axi_read(dut, 0x0C)
    assert status == 0, f"Status should be 0 after ctrl clear, got {status}"


@cocotb.test()
async def test_axi_lite_partial_wstrb_data_in(dut):
    clock = Clock(dut.ACLK, 10, units="ns")
    clock.start(start_high=False)
    await reset_dut(dut)
    await axi_write(dut, 0x04, 0x11223344, 0xF)
    # WSTRB[1]=1 updates byte1 [15:8]; WDATA[15:8]=0xAA -> 0x1122AA44 (not WSTRB[2]).
    await axi_write(dut, 0x04, 0x0000AA00, 0x02)
    await axi_write(dut, 0x00, 1)
    # PIPE_LEN + margin (see PIPE_CYC); partial-merge + pipeline needs full delay vs fixed 50.
    await _wait_after_ctrl_pulse(dut)
    await _wait_cycles(dut, 10)
    merged = 0x1122AA44
    result = await axi_read(dut, 0x08)
    expected = compute_expected(merged)
    assert result == expected, f"DATA_OUT was {result}, expected {expected} for merged {merged:#x}"


@cocotb.test()
async def test_axi_lite_read_unmapped_addr(dut):
    clock = Clock(dut.ACLK, 10, units="ns")
    clock.start(start_high=False)
    await reset_dut(dut)
    _data, rresp = await axi_read_with_resp(dut, 0x14)
    assert rresp == 2, f"Read of unmapped addr must return SLVERR (2), got {rresp}"


@cocotb.test()
async def test_axi_lite_ctrl_rising_edge_only(dut):
    """DATA_OUT must change only on CTRL[0] rising edge, not while CTRL stays high."""
    clock = Clock(dut.ACLK, 10, units="ns")
    clock.start(start_high=False)
    await reset_dut(dut)

    # Trigger with ctrl=1 after setting data_in=5.
    await axi_write(dut, 0x04, 5)
    await axi_write(dut, 0x00, 1)
    await _wait_after_ctrl_pulse(dut)

    out1 = await axi_read(dut, 0x08)
    st1 = await axi_read(dut, 0x0C)
    assert st1 == 1, f"STATUS should be 1 after CTRL rising edge, got {st1}"
    assert out1 == compute_expected(5), f"DATA_OUT should match data_in=5, got {out1}"

    # Update data_in while leaving CTRL[0]=1 asserted -> DATA_OUT must NOT change.
    await axi_write(dut, 0x04, 6)
    await _wait_cycles(dut, 30)

    # Writing CTRL=1 again while CTRL[0] is already 1 must NOT retrigger.
    await axi_write(dut, 0x00, 1)
    await _wait_cycles(dut, 30)

    out2 = await axi_read(dut, 0x08)
    st2 = await axi_read(dut, 0x0C)
    assert st2 == 1, f"STATUS must remain 1 while CTRL[0] is still high, got {st2}"
    assert out2 == compute_expected(5), f"DATA_OUT must remain frozen until next CTRL edge, got {out2}"

    # Clear CTRL then set again -> new transform should occur.
    await axi_write(dut, 0x00, 0)
    await _wait_cycles(dut, 10)
    st3 = await axi_read(dut, 0x0C)
    assert st3 == 0, f"STATUS should clear when CTRL[0] is cleared, got {st3}"

    await axi_write(dut, 0x00, 1)
    await _wait_after_ctrl_pulse(dut)
    out3 = await axi_read(dut, 0x08)
    assert out3 == compute_expected(6), f"DATA_OUT should update after second CTRL edge, got {out3}"


@cocotb.test()
async def test_axi_lite_rvalid_holds_when_rready_low(dut):
    """RVALID must remain asserted and RDATA stable until RREADY handshake."""
    clock = Clock(dut.ACLK, 10, units="ns")
    clock.start(start_high=False)
    await reset_dut(dut)

    await axi_write(dut, 0x04, 12)
    await axi_write(dut, 0x00, 1)
    await _wait_after_ctrl_pulse(dut)

    dut.RREADY.value = 0
    dut.ARADDR.value = 0x08
    dut.ARVALID.value = 1

    for _ in range(50):
        await RisingEdge(dut.ACLK)
        if dut.ARREADY.value == 1:
            break
    dut.ARVALID.value = 0

    # Wait for RVALID to assert.
    for _ in range(50):
        await RisingEdge(dut.ACLK)
        if dut.RVALID.value == 1:
            break

    held_data = dut.RDATA.value.integer
    held_rresp = dut.RRESP.value.integer
    for _ in range(6):
        await RisingEdge(dut.ACLK)
        assert dut.RVALID.value == 1, "RVALID deasserted while RREADY=0"
        assert dut.RDATA.value.integer == held_data, "RDATA changed while RVALID was held"
        assert dut.RRESP.value.integer == held_rresp, "RRESP changed while RVALID was held"

    dut.RREADY.value = 1
    await RisingEdge(dut.ACLK)
    await RisingEdge(dut.ACLK)
    assert dut.RVALID.value == 0, "RVALID should clear after RREADY handshake"


@cocotb.test()
async def test_axi_lite_ctrl_wstrb_masks_bit0(dut):
    """CTRL[0] must only update when WSTRB[0]=1."""
    clock = Clock(dut.ACLK, 10, units="ns")
    clock.start(start_high=False)
    await reset_dut(dut)

    await axi_write(dut, 0x04, 9)  # data_in only

    # Attempt to set CTRL bit0 with WSTRB[0]=0 -> should not trigger.
    await axi_write(dut, 0x00, 1, wstrb=0x0)
    await _wait_cycles(dut, 30)
    st0 = await axi_read(dut, 0x0C)
    assert st0 == 0, f"STATUS must remain 0 when CTRL bit0 was masked off, got {st0}"

    # Now set CTRL bit0 with WSTRB[0]=1 -> should trigger.
    await axi_write(dut, 0x00, 1, wstrb=0x1)
    await _wait_after_ctrl_pulse(dut)
    st1 = await axi_read(dut, 0x0C)
    out1 = await axi_read(dut, 0x08)
    assert st1 == 1, f"STATUS should be 1 after masked write then valid CTRL write, got {st1}"
    assert out1 == compute_expected(9), f"DATA_OUT mismatch after CTRL trigger, got {out1}"


@cocotb.test()
async def test_axi_lite_ctrl_clear_masked_by_wstrb(dut):
    """If WSTRB[0]=0 on a write of CTRL=0, CTRL[0] must remain set."""
    clock = Clock(dut.ACLK, 10, units="ns")
    clock.start(start_high=False)
    await reset_dut(dut)

    # Set CTRL=1 (and compute output) using a known data_in.
    await axi_write(dut, 0x04, 5)
    await axi_write(dut, 0x00, 1, wstrb=0x1)
    await _wait_after_ctrl_pulse(dut)

    st1 = await axi_read(dut, 0x0C)
    out1 = await axi_read(dut, 0x08)
    assert st1 == 1, f"STATUS should be 1 after CTRL set, got {st1}"
    assert out1 == compute_expected(5), f"DATA_OUT mismatch after CTRL set, got {out1}"

    # Attempt to clear CTRL[0] but mask WSTRB[0]=0.
    await axi_write(dut, 0x00, 0, wstrb=0x0)
    await _wait_cycles(dut, 30)

    st2 = await axi_read(dut, 0x0C)
    out2 = await axi_read(dut, 0x08)
    assert st2 == 1, f"STATUS must remain 1 when CTRL clear is masked, got {st2}"
    assert out2 == compute_expected(5), f"DATA_OUT must remain frozen when CTRL clear is masked, got {out2}"

    # Now clear CTRL[0] properly and verify status drops.
    await axi_write(dut, 0x00, 0, wstrb=0x1)
    await _wait_cycles(dut, 20)
    st3 = await axi_read(dut, 0x0C)
    assert st3 == 0, f"STATUS should be 0 after proper CTRL clear, got {st3}"


@cocotb.test()
async def test_axi_lite_unmapped_write_slverr(dut):
    """Unmapped writes should return SLVERR on BRESP."""
    clock = Clock(dut.ACLK, 10, units="ns")
    clock.start(start_high=False)
    await reset_dut(dut)

    bresp = await axi_write_resp(dut, 0x10, 0x1234, wstrb=0xF)
    assert bresp == 2, f"Unmapped write should return SLVERR (2), got {bresp}"


@cocotb.test()
async def test_axi_lite_write_read_only_data_out_slverr(dut):
    """Writes to DATA_OUT (0x08) must be decode errors (SLVERR)."""
    clock = Clock(dut.ACLK, 10, units="ns")
    clock.start(start_high=False)
    await reset_dut(dut)
    bresp = await axi_write_resp(dut, 0x08, 0xDEADBEEF, wstrb=0xF)
    assert bresp == 2, f"Write to 0x08 must return SLVERR (2), got {bresp}"


@cocotb.test()
async def test_axi_lite_write_read_only_status_slverr(dut):
    """Writes to STATUS (0x0C) must be decode errors (SLVERR)."""
    clock = Clock(dut.ACLK, 10, units="ns")
    clock.start(start_high=False)
    await reset_dut(dut)
    bresp = await axi_write_resp(dut, 0x0C, 1, wstrb=0xF)
    assert bresp == 2, f"Write to 0x0C must return SLVERR (2), got {bresp}"


@cocotb.test()
async def test_axi_lite_ctrl_byte1_only_does_not_start(dut):
    """WSTRB must select bytes: writing only byte1 must not set CTRL[0] or start datapath."""
    clock = Clock(dut.ACLK, 10, units="ns")
    clock.start(start_high=False)
    await reset_dut(dut)
    await axi_write(dut, 0x04, 42)
    # Only update ctrl_reg[15:8] with 0x01; CTRL[0] stays 0.
    await axi_write(dut, 0x00, 0x00000100, wstrb=0x02)
    await _wait_cycles(dut, 30)
    st = await axi_read(dut, 0x0C)
    assert st == 0, f"STATUS must stay 0 when CTRL[0] was not written, got {st}"
    out = await axi_read(dut, 0x08)
    assert out == 0, f"DATA_OUT must stay 0 without CTRL start, got {out}"
    # Proper start on byte0.
    await axi_write(dut, 0x00, 1, wstrb=0x01)
    await _wait_after_ctrl_pulse(dut)
    out2 = await axi_read(dut, 0x08)
    assert out2 == compute_expected(42), f"After real CTRL start, DATA_OUT wrong: {out2}"


@cocotb.test()
async def test_axi_lite_reset_clears_regs_after_run(dut):
    """ARESETn must clear CTRL/DATA_OUT/STATUS even after a completed operation."""
    clock = Clock(dut.ACLK, 10, units="ns")
    clock.start(start_high=False)
    await reset_dut(dut)
    await axi_write(dut, 0x04, 11)
    await axi_write(dut, 0x00, 1)
    await _wait_after_ctrl_pulse(dut)
    await reset_dut(dut)
    ctrl = await axi_read(dut, 0x00)
    st = await axi_read(dut, 0x0C)
    dout = await axi_read(dut, 0x08)
    din = await axi_read(dut, 0x04)
    assert ctrl == 0, f"CTRL should be 0 after reset, got {ctrl}"
    assert st == 0, f"STATUS should be 0 after reset, got {st}"
    assert dout == 0, f"DATA_OUT should be 0 after reset, got {dout}"
    assert din == 0, f"DATA_IN should be 0 after reset, got {din}"


@cocotb.test()
async def test_axi_lite_mapped_write_bresp_ok(dut):
    """Mapped register writes must complete with OKAY (BRESP=0), not SLVERR."""
    clock = Clock(dut.ACLK, 10, units="ns")
    clock.start(start_high=False)
    await reset_dut(dut)
    b0 = await axi_write_resp(dut, 0x04, 0x55, wstrb=0xF)
    assert b0 == 0, f"Write DATA_IN should be OKAY (0), got {b0}"
    b1 = await axi_write_resp(dut, 0x00, 1, wstrb=0x1)
    assert b1 == 0, f"Write CTRL should be OKAY (0), got {b1}"


@cocotb.test()
async def test_axi_lite_two_reads_same_data_out(dut):
    """Two consecutive reads of DATA_OUT must return the same value (no spurious toggle)."""
    clock = Clock(dut.ACLK, 10, units="ns")
    clock.start(start_high=False)
    await reset_dut(dut)
    await axi_write(dut, 0x04, 88)
    await axi_write(dut, 0x00, 1)
    await _wait_after_ctrl_pulse(dut)
    a = await axi_read(dut, 0x08)
    b = await axi_read(dut, 0x08)
    exp = compute_expected(88)
    assert a == exp and b == exp, f"Reads got {a}, {b}, expected {exp}, {exp}"


@cocotb.test()
async def test_axi_lite_read_mapped_after_slverr_read(dut):
    """After SLVERR on unmapped read, a following mapped read must still be OKAY."""
    clock = Clock(dut.ACLK, 10, units="ns")
    clock.start(start_high=False)
    await reset_dut(dut)
    _d0, r0 = await axi_read_with_resp(dut, 0x18)
    assert r0 == 2, f"Unmapped read should SLVERR, got {r0}"
    _d1, r1 = await axi_read_with_resp(dut, 0x00)
    assert r1 == 0, f"Mapped read after SLVERR should be OKAY (0), got {r1}"


def test_axi_lite_slave_hidden_runner():
    sim = os.getenv("SIM", "icarus")
    proj_path = Path(__file__).resolve().parent.parent
    sources = [proj_path / "sources/axi_lite_slave.sv"]
    from cocotb_tools.runner import get_runner
    runner = get_runner(sim)
    runner.build(sources=sources, hdl_toplevel="axi_lite_slave", always=True)
    runner.test(hdl_toplevel="axi_lite_slave", test_module="test_axi_lite_slave_hidden")
