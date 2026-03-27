# Agent Evaluation Framework Template

## Overview

This is a template framework for creating and evaluating AI agent tasks. It provides a structured approach to:
- Define coding tasks with clear specifications
- Grade agent solutions automatically using test-based validation
- Manage multiple task difficulties (easy, medium, hard)
- Run tasks in isolated environments with proper grading

## Project Structure

```
.
├── src/hud_controller/          # Main framework code
│   ├── app.py                   # Main MCP server and entry points
│   ├── spec.py                  # Core specifications (Problem, Grade, Grader)
│   ├── grading_runner.py        # Test execution and grading logic
│   ├── utils.py                 # Utility functions
│   ├── setup.py                 # Environment setup
│   ├── problems/                # Task definitions by difficulty
│   │   ├── basic.py             # Easy difficulty tasks
│   └── tools/                   # MCP tools for testing
│       ├── base.py              # Base tool definitions
│       ├── bash.py              # Bash execution
│       ├── edit.py              # File editing
│       └── run.py               # Command running
├── pyproject.toml               # Python package configuration
├── Dockerfile                   # Container setup
└── README.md                    # This file
```

## Core Concepts

### 1. Problem Definition

Problems are defined using the `ProblemSpec` data class with these key fields:

```python
    ProblemSpec(
        id="simple_counter", # the unique ID of the problem
        description="""Please implement a simple synchronous counter that with reset, enable, and load functionality.
Inputs:
clk - Clock signal (triggers on rising edge)
rst - Synchronous reset signal
ena - Enable signal (allows counting)
set - Load signal (sets counter to a specific value)
din - 8-bit data input (value to load when set is high)
Output:
counter - 8-bit counter value        
        
""", # What you want the agent to do
        difficulty="easy", # how difficult the problem is
        # the branch names
        base="simple_counter_baseline", 
        test="simple_counter_test",
        golden="simple_counter_golden",
        test_files=["tests/test_simple_counter_hidden.py"]
    )
```

### 2. Test-Based Validation

Tasks are graded by:
1. Copying the repository (including whatever changes the agent made) to a clean workspace
2. Applying the agent's solution patch
3. Applying a test patch on top of what the agent did (adds tests that would fail in an unmodified repo)
4. Running `pytest <test files>` to test the build 

## Creating New Tasks

### Step 1: Prepare Git Branches

You need three branches in your target repository (the one that we clone in the dockerfile):

1. **baseline** - Starting state with the bug/missing feature
2. **test** - Adds tests that should fail on baseline, and pass in golden branch
3. **golden** - Contains the correct solution (for reference). Notably, this should not contain the tests.

### Step 2: Define the Task

We currently only have src/hud_controller/problems/basic.py, but feel free to make more files in the subdirectory.
Once you do that, you can add a problem to the registry as follows:

```python
PROBLEM_REGISTRY.append(
    ProblemSpec(
        id="simple_counter",
        description="""Please implement a simple synchronous counter that with reset, enable, and load functionality.
Inputs:
clk - Clock signal (triggers on rising edge)
rst - Synchronous reset signal
ena - Enable signal (allows counting)
set - Load signal (sets counter to a specific value)
din - 8-bit data input (value to load when set is high)
Output:
counter - 8-bit counter value        
        
""",
        difficulty="easy",
        base="simple_counter_baseline",
        test="simple_counter_test",
        golden="simple_counter_golden",
        test_files=["tests/test_simple_counter_hidden.py"],
    )
)
```

The base, test, and golden branches must correspond to the branches you created in the first step. 

### Step 3: Validate your problem

It's important to ensure that your problems pass a basic sanity check:
* All tests at the baseline branch should pass
* When we apply the hidden test set, the hidden tests should fail
* When we apply the golden patch and then apply the hidden test set, all tests should pass

To help you with this, we have a script called `utils/imagectl3.py`.

To run and build the images you can do:
```bash
uv run utils/imagectl3.py --build --validate
```
You can specify the exact image you want to test with the `--ids` flag. 
You can also make this easier to type by using the shorform `-b` flag for `--build` and the shortform `-v` flag for `--validate`.
```bash
uv run utils/imagectl3.py -bv --ids simple_counter
```
Note: ensure your image is built before you try to validate it.

## Running Tasks

### Setup Environment

```bash
uv sync
```
### Build, Validate all problems and generate Json

```bash
uv run utils/imagectl3.py verilog_ -bvj
```
This will build all the docker images, with the prefix `verilog_` and then run the validation workflow. 
Once you get a lot of problems, you'll find it helpful to do building and validation in parallel with `--jobs`:
```bash
uv run utils/imagectl3.py verilog_ -bvj --jobs 4
```

### Run hud eval locally
Generate task JSON first (`imagectl3` with `-j`), then run eval. Example:
```bash
uv run hud eval local-hud.json claude --max-steps 50
```

### Run hud eval remotely
You can run them remotely too! However, you'll need to push the images. T
To make this easier, we have the `--push` or `-p` flag in imagectl3. 
Note that we also change the image prefix to make it pushable to docker hub.
```bash
uv run utils/imagectl3.py govindhud/verilog_ -bvjp --jobs 4
```
Once all images are pushed, we can:
```bash
uv run hud eval remote-hud.json claude --max-steps 50
```


## Configuration

### Target Repository Dependency

The framework clones a **target Verilog repository** that contains the problems to be solved. This is configured in two places:

1. **Dockerfile:** `ARG REPO_URL=...` and the clone into `/home/ubuntu/example-verilog-codebase` (see the `RUN git clone ... example-verilog-codebase` block).

2. **`grading_runner.py`:** Must match that clone path:
   ```python
   self.original_repo_path = "/home/ubuntu/example-verilog-codebase"
   ```

**Important:** When making changes to the remote repository, ALWAYS increment the `random` variable in the Dockerfile to force Docker to re-clone:
```dockerfile
ENV random=random23  # Increment this number when you change the target repo or branches
```

### Environment Variables

Key environment variables used by the grading system:

- `MCP_TESTING_MODE` - Enable testing tools (default: "1")
- `NODE_ENV` - Node environment (set to "test" for testing)
- `PROBLEM_ID` - The specific problem being evaluated
- `HINTS` - Hint level for the problem
- `OTEL_SDK_DISABLED` - Set to `true` to disable HUD OpenTelemetry uploads when offline or when DNS to the telemetry host fails (see also `hud-patched` entrypoint, which defaults this when unset). Set to `false` to allow telemetry.
- `GRADING_PYTEST_TIMEOUT` - Optional seconds (float) for pytest/cocotb in `grading_runner`. If unset, behavior matches the previous unlimited wait.

### Docker Configuration

The included `Dockerfile` sets up the complete environment:
- Base system with required tools
- Verilog toolchain (iverilog, verilator)
- Python test framework (pytest, cocotb)
- VNC for GUI testing (if needed)


## Best Practices

### Task Design

1. **Clear Descriptions**: Provide detailed, unambiguous task descriptions
2. **Focused Scope**: Each task should test one concept or skill
3. **Realistic Scenarios**: Base tasks on real-world debugging/development scenarios
4. **Fair Hints**: If providing hints, ensure they guide without giving away the solution

### Test Design

1. **Comprehensive Coverage**: Tests should fully validate the requirement
2. **Clear Failures**: Test failures should clearly indicate what's wrong
3. **Minimal Changes**: Test patches should only add tests, not modify existing code
4. **Isolation**: Tests should not depend on external state

### Branch Management

1. **Clean Baseline**: Baseline should be stable and buildable
2. **Minimal Test Patch**: Only add tests that verify the specific requirement
3. **Correct Golden**: Golden solution should be minimal and idiomatic
