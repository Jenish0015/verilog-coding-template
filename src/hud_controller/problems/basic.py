"""
Example problem registry for verilog evaluation template.
For internal problems, use phinitylabs/verilog-eval-internal.
"""
import logging
from hud_controller.spec import HintSpec, ProblemSpec, PROBLEM_REGISTRY

logger = logging.getLogger(__name__)

# =============================================================================
# EXAMPLE PROBLEMS - For demonstration only
# =============================================================================

PROBLEM_REGISTRY.append(
    ProblemSpec(
        id="axi_lite_slave",
        description="""Complete the AXI4-Lite slave in `sources/axi_lite_slave.sv` without changing the port list.

The checked-in baseline is intentionally incomplete. Add the missing RTL so the design behaves as a lawful AXI4-Lite slave for this repository: correct reset, protocol-compliant read and write channels, byte-wise `WSTRB` handling for register writes, address decode with appropriate `BRESP`/`RRESP` (including decode errors on unmapped addresses), and the control/status semantics implied by the hidden cocotb tests. The datapath is not combinational: the operand is defined at the `CTRL[0]` rising edge and the result becomes visible on `DATA_OUT` only after a fixed multi-cycle delay; the tests are the only full specification of correctness.
""",
        difficulty="hard",
        base="axi_lite_slave_baseline",
        test="axi_lite_slave_test",
        golden="axi_lite_slave_golden",
        test_files=["tests/test_axi_lite_slave_hidden.py"],
        hints=[
            HintSpec(
                hint_type="legit",
                text="Apply each byte of `WDATA` to a register only when the matching `WSTRB` bit is set. Writes that do not enable the byte lane for a control bit (e.g. `CTRL[0]`) must not start, re-trigger, or clear behavior that depends on that bit.",
                why_legitmate="Standard AXI-Lite byte strobes; avoids trivial mistakes without naming addresses or timing.",
            ),
            HintSpec(
                hint_type="legit",
                text="Return `SLVERR` on `BRESP`/`RRESP` when the address is not mapped for that operation, or when a write targets a read-only register; mapped reads and writes should complete with `OKAY`.",
                why_legitmate="Documents expected AXI response semantics for decode/read-only errors without leaking the register map.",
            ),
        ],
    )
)
