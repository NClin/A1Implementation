# "A1" Smart Contract Security Analysis Tool

A defensive cybersecurity tool that uses LLMs to automatically analyze smart contracts for vulnerabilities. This implementation is based on the A1 research paper for internal security testing purposes, and achieves similar results.

Implements the "A1" security tool described at: https://arxiv.org/abs/2507.05558

The A1 security tool targets a smart contract and uses an agent extract the smart contract, analyze the source, iteratively test potential exploits in a Foundry execution environment with consistently-constructed context, and assess the potential revenue of a successful exploit.

**FOR DEFENSIVE USE ONLY** - This tool is intended for:
- Auditing contracts you own or have permission to test
- Academic purposes

The original paper performs extensive revenue cost/benefit analysis, however this implementation does not optimize context or accurately gauge revenue as that would consistute a full automated attack vector. As the paper's authors didn't release their code, I felt it unwise to continue to reproduce that aspect of the paper.

## Installation

```bash
# Clone the repository
git clone <your-repo>
cd A1implementation

# Install dependencies
pip install -r requirements.txt

# Install Foundry (required for execution testing)
curl -L https://foundry.paradigm.xyz | bash
foundryup
```

## Environment Setup

Create a `.env` file with your API keys:

```bash
# Required
OPENROUTER_API_KEY=your_openrouter_key
ETHEREUM_RPC_URL=your_ethereum_rpc_url
ETHERSCAN_API_KEY=your_etherscan_key

# Optional (for BSC analysis)
BSC_RPC_URL=your_bsc_rpc_url
```

## Usage

### Single Contract Analysis

```bash
# Analyze a single contract
python main.py --chain 1 --address 0x1234...

# Analyze at a specific historical block
python main.py --chain 1 --address 0x1234... --block 18000000

# Use a different model
python main.py --chain 1 --address 0x1234... --model "anthropic/claude-sonnet-4"
```

### Batch Analysis

Create a JSON file with multiple contracts:

```json
[
  {
    "chain_id": 1,
    "address": "0x1234...",
    "block_number": 18000000
  },
  {
    "chain_id": 56, 
    "address": "0x5678..."
  }
]
```

Run batch analysis:
```bash
python main.py --contract-list contracts.json
```

Run VERITE dataset (target ~62% success as per implementation paper)
```bash
python main.py --contract-list verite_validation_contracts.json
```

## Core Functionality

The A1 system analyzes smart contracts through:

1. **Source Code Retrieval**: Gets verified source code from block explorers
2. **State Analysis**: Queries contract state at specific blocks
3. **Vulnerability Detection**: Uses LLMs to identify potential exploits
4. **Exploit Validation**: Tests exploits in sandboxed environments using Foundry
5. **Revenue Calculation**: Evaluates economic impact of discovered vulnerabilities

## Supported Chains

- **Ethereum (chain_id: 1)**: Full support
- **BSC (chain_id: 56)**: Full support

## Output

Analysis results are saved to:
- **Console**: Real-time progress and summary
- **JSON file**: Detailed findings (`a1_results.json` by default)
- **Log file**: Complete execution trace (`a1_system.log`)

Example successful analysis:
```
🚨 VULNERABILITY FOUND!
   Revenue: 1.2500 ETH ($3,125.00)
   Type: reentrancy
   Iterations: 3
   Cost: $0.85
   Time: 12.3s
```

## Configuration

Key settings can be modified in `a1_system/config.py`:

- `default_model`: LLM model to use (default: "anthropic/claude-sonnet-4")
- `max_iterations`: Maximum analysis attempts per contract (default: 3)
- `max_cost_per_analysis`: USD spending limit per contract (default: 5.0)
- `analysis_timeout`: Maximum time per analysis in seconds (default: 1800)
