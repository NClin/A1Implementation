"""
Balance Invariant Validator for A1 Paper Compliance
Ensures balance invariant ∀t : Bf(t) ≥ Bi(t) is enforced
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import logging
from .tokens import TokenRegistry


@dataclass
class BalanceInvariantViolation:
    """Represents a balance invariant violation"""
    token_symbol: str
    token_address: str
    initial_balance: float
    final_balance: float
    violation_amount: float
    chain_id: int
    violation_type: str  # "depletion", "negative_balance", "insufficient_funds"


class BalanceInvariantValidator:
    """
    Validates balance invariants according to A1 paper methodology
    
    From Section IV.D: "To ensure no artificial revenue from token depletion,
    we enforce the balance invariant ∀t : Bf(t) ≥ Bi(t)"
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # Initial balances per paper specification
        self.PAPER_INITIAL_BALANCES = {
            1: {  # Ethereum
                "ETH": 1e5,       # 100,000 ETH
                "WETH": 1e5,      # 100,000 WETH  
                "USDC": 1e7,      # 10,000,000 USDC
                "USDT": 1e7,      # 10,000,000 USDT
                "DAI": 1e7        # 10,000,000 DAI
            },
            56: {  # BSC
                "BNB": 1e5,       # 100,000 BNB
                "WBNB": 1e5,      # 100,000 WBNB
                "USDT": 1e7,      # 10,000,000 USDT
                "BUSD": 1e7       # 10,000,000 BUSD
            }
        }
    
    def validate_balance_invariant(self, balance_changes: List[Dict], 
                                 chain_id: int) -> Tuple[bool, List[BalanceInvariantViolation]]:
        """
        Validate balance invariant for a set of balance changes
        
        Args:
            balance_changes: List of balance change dictionaries
            chain_id: Blockchain ID
            
        Returns:
            Tuple of (is_valid, violations_list)
        """
        violations = []
        
        for change in balance_changes:
            token_symbol = change.get("token", "UNKNOWN")
            initial_balance = change.get("initial", 0.0)
            final_balance = change.get("final", 0.0)
            
            # Check basic balance invariant: Bf(t) ≥ Bi(t)
            if final_balance < initial_balance:
                token_info = TokenRegistry.get_token_info(chain_id, token_symbol)
                token_address = token_info.address if token_info else ""
                
                violations.append(BalanceInvariantViolation(
                    token_symbol=token_symbol,
                    token_address=token_address,
                    initial_balance=initial_balance,
                    final_balance=final_balance,
                    violation_amount=initial_balance - final_balance,
                    chain_id=chain_id,
                    violation_type="depletion"
                ))
            
            # Check for negative balances
            if final_balance < 0:
                token_info = TokenRegistry.get_token_info(chain_id, token_symbol)
                token_address = token_info.address if token_info else ""
                
                violations.append(BalanceInvariantViolation(
                    token_symbol=token_symbol,
                    token_address=token_address,
                    initial_balance=initial_balance,
                    final_balance=final_balance,
                    violation_amount=abs(final_balance),
                    chain_id=chain_id,
                    violation_type="negative_balance"
                ))
        
        is_valid = len(violations) == 0
        return is_valid, violations
    
    def validate_paper_compliance(self, balance_changes: List[Dict], 
                                 chain_id: int) -> Tuple[bool, List[BalanceInvariantViolation]]:
        """
        Validate compliance with A1 paper's initial balance requirements
        
        Args:
            balance_changes: List of balance change dictionaries
            chain_id: Blockchain ID
            
        Returns:
            Tuple of (is_compliant, violations_list)
        """
        violations = []
        paper_balances = self.PAPER_INITIAL_BALANCES.get(chain_id, {})
        
        for change in balance_changes:
            token_symbol = change.get("token", "UNKNOWN")
            initial_balance = change.get("initial", 0.0)
            final_balance = change.get("final", 0.0)
            
            # Check if token should have paper-specified initial balance
            if token_symbol in paper_balances:
                expected_initial = paper_balances[token_symbol]
                
                # Allow some tolerance for floating point precision
                if abs(initial_balance - expected_initial) > 1e-6:
                    self.logger.warning(
                        f"Initial balance deviation for {token_symbol}: "
                        f"expected {expected_initial}, got {initial_balance}"
                    )
                
                # Check if final balance violates paper requirements
                if final_balance < expected_initial:
                    token_info = TokenRegistry.get_token_info(chain_id, token_symbol)
                    token_address = token_info.address if token_info else ""
                    
                    violations.append(BalanceInvariantViolation(
                        token_symbol=token_symbol,
                        token_address=token_address,
                        initial_balance=expected_initial,
                        final_balance=final_balance,
                        violation_amount=expected_initial - final_balance,
                        chain_id=chain_id,
                        violation_type="insufficient_funds"
                    ))
        
        is_compliant = len(violations) == 0
        return is_compliant, violations
    
    def get_enforcement_suggestions(self, violations: List[BalanceInvariantViolation]) -> List[str]:
        """
        Get suggestions for enforcing balance invariants
        
        Args:
            violations: List of balance invariant violations
            
        Returns:
            List of enforcement suggestions
        """
        suggestions = []
        
        for violation in violations:
            if violation.violation_type == "depletion":
                suggestions.append(
                    f"⚠️  {violation.token_symbol}: Add {violation.violation_amount:.6f} to initial balance "
                    f"to prevent depletion (current: {violation.initial_balance:.6f})"
                )
            
            elif violation.violation_type == "negative_balance":
                suggestions.append(
                    f"❌ {violation.token_symbol}: Balance went negative ({violation.final_balance:.6f}). "
                    f"Increase initial balance by at least {violation.violation_amount:.6f}"
                )
            
            elif violation.violation_type == "insufficient_funds":
                suggestions.append(
                    f"📋 {violation.token_symbol}: Paper requires {violation.initial_balance:.0f} initial balance. "
                    f"Current exploit would deplete {violation.violation_amount:.6f}"
                )
        
        return suggestions
    
    def generate_compliance_report(self, balance_changes: List[Dict], 
                                  chain_id: int) -> Dict:
        """
        Generate comprehensive compliance report
        
        Args:
            balance_changes: List of balance change dictionaries
            chain_id: Blockchain ID
            
        Returns:
            Compliance report dictionary
        """
        # Basic balance invariant validation
        invariant_valid, invariant_violations = self.validate_balance_invariant(
            balance_changes, chain_id
        )
        
        # Paper compliance validation
        paper_compliant, paper_violations = self.validate_paper_compliance(
            balance_changes, chain_id
        )
        
        # Generate suggestions
        all_violations = invariant_violations + paper_violations
        suggestions = self.get_enforcement_suggestions(all_violations)
        
        return {
            "balance_invariant_enforced": invariant_valid,
            "paper_methodology_compliant": paper_compliant,
            "total_violations": len(all_violations),
            "invariant_violations": [
                {
                    "token": v.token_symbol,
                    "address": v.token_address,
                    "initial": v.initial_balance,
                    "final": v.final_balance,
                    "violation": v.violation_amount,
                    "type": v.violation_type
                }
                for v in invariant_violations
            ],
            "paper_compliance_violations": [
                {
                    "token": v.token_symbol,
                    "address": v.token_address,
                    "expected_initial": v.initial_balance,
                    "actual_final": v.final_balance,
                    "violation": v.violation_amount,
                    "type": v.violation_type
                }
                for v in paper_violations
            ],
            "enforcement_suggestions": suggestions,
            "paper_initial_balances": self.PAPER_INITIAL_BALANCES.get(chain_id, {}),
            "methodology_reference": "A1 Paper Section IV.D - Balance Invariant Enforcement"
        }
    
    def calculate_minimum_required_balances(self, balance_changes: List[Dict], 
                                          chain_id: int) -> Dict[str, float]:
        """
        Calculate minimum required initial balances to avoid violations
        
        Args:
            balance_changes: List of balance change dictionaries
            chain_id: Blockchain ID
            
        Returns:
            Dictionary of token_symbol -> minimum_required_balance
        """
        minimum_balances = {}
        
        for change in balance_changes:
            token_symbol = change.get("token", "UNKNOWN")
            initial_balance = change.get("initial", 0.0)
            final_balance = change.get("final", 0.0)
            net_change = change.get("net_change", final_balance - initial_balance)
            
            if net_change < 0:  # Token is being spent
                # Minimum required = amount spent + safety buffer
                minimum_required = abs(net_change) * 1.1  # 10% safety buffer
                minimum_balances[token_symbol] = minimum_required
        
        return minimum_balances