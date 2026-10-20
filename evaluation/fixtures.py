"""
Evaluation Fixtures Generator for RepoSage (Phase 6F).

Creates self-contained, deterministic repositories on disk for testing
ingestion, AST intelligence, call graphs, blast radius, hybrid retrieval,
cache mechanics, multi-repo isolation, and LLM grounding.
"""

import os
from pathlib import Path
from typing import Any


def create_python_fixture(base_dir: Path) -> Path:
    """Create a deterministic Python repository."""
    repo_dir = base_dir / "eval_python_repo"
    (repo_dir / "services").mkdir(parents=True, exist_ok=True)
    (repo_dir / "utils").mkdir(parents=True, exist_ok=True)

    (repo_dir / "utils" / "validators.py").write_text('''
"""Validation utilities."""

def validate_amount(amount: float) -> bool:
    """Check if amount is greater than zero."""
    if amount <= 0:
        raise ValueError("Amount must be positive")
    return True

def format_currency(amount: float, currency: str = "USD") -> str:
    """Format amount as string."""
    return f"{currency} {amount:.2f}"
'''.strip(), encoding="utf-8")

    (repo_dir / "services" / "payment.py").write_text('''
"""Payment service module."""
from utils.validators import validate_amount, format_currency

class PaymentProcessor:
    """Processes customer transactions."""

    def __init__(self, merchant_id: str):
        self.merchant_id = merchant_id

    def process_payment(self, amount: float, account_id: str) -> dict:
        """Process a single transaction."""
        validate_amount(amount)
        self.log_payment(amount, account_id)
        return {"status": "success", "amount": amount}

    def log_payment(self, amount: float, account_id: str) -> None:
        """Internal logger method."""
        formatted = format_currency(amount)
'''.strip(), encoding="utf-8")

    (repo_dir / "services" / "checkout.py").write_text('''
"""Checkout orchestration."""
from services.payment import PaymentProcessor

def checkout(cart_total: float, user_id: str) -> dict:
    """Execute complete checkout flow."""
    processor = PaymentProcessor("merchant_001")
    return processor.process_payment(cart_total, user_id)
'''.strip(), encoding="utf-8")

    (repo_dir / "README.md").write_text("# Python Evaluation Repository\nContains payments and checkout services.", encoding="utf-8")
    return repo_dir


def create_jsts_fixture(base_dir: Path) -> Path:
    """Create a deterministic JavaScript/TypeScript/TSX repository."""
    repo_dir = base_dir / "eval_jsts_repo"
    (repo_dir / "src" / "components").mkdir(parents=True, exist_ok=True)
    (repo_dir / "src" / "services").mkdir(parents=True, exist_ok=True)
    (repo_dir / "src" / "utils").mkdir(parents=True, exist_ok=True)

    (repo_dir / "src" / "utils" / "validation.ts").write_text('''
export interface ValidationResult {
    isValid: boolean;
    errorCode?: string;
}

export type Amount = number;

export enum Currency {
    USD = "USD",
    EUR = "EUR",
}

export function validateAmount(amount: Amount): ValidationResult {
    if (amount <= 0) {
        return { isValid: false, errorCode: "INVALID_AMOUNT" };
    }
    return { isValid: true };
}

export const formatCurrency = (amount: Amount, currency: Currency = Currency.USD): string => {
    return `${currency} ${amount.toFixed(2)}`;
};
'''.strip(), encoding="utf-8")

    (repo_dir / "src" / "services" / "paymentService.ts").write_text('''
import { validateAmount, formatCurrency, Currency, Amount } from "../utils/validation";

export class PaymentService {
    private apiKey: string;

    constructor(apiKey: string) {
        this.apiKey = apiKey;
    }

    public processPayment(amount: Amount): boolean {
        this.auditLog(amount);
        const res = validateAmount(amount);
        return res.isValid;
    }

    private auditLog(amount: Amount): void {
        const msg = formatCurrency(amount, Currency.USD);
    }
}

export default PaymentService;
'''.strip(), encoding="utf-8")

    (repo_dir / "src" / "components" / "CheckoutButton.tsx").write_text('''
import React from "react";
import PaymentService from "../services/paymentService";

export interface CheckoutProps {
    amount: number;
    onCompleted: () => void;
}

export const CheckoutButton: React.FC<CheckoutProps> = ({ amount, onCompleted }) => {
    const handlePay = () => {
        const svc = new PaymentService("key_live");
        if (svc.processPayment(amount)) {
            onCompleted();
        }
    };

    return (
        <button onClick={handlePay} className="btn-pay">
            Pay Now
        </button>
    );
};
'''.strip(), encoding="utf-8")

    (repo_dir / "src" / "legacyHandler.js").write_text('''
const { validateAmount } = require("./utils/validation");

function legacyHandler(amount) {
    return validateAmount(amount);
}

module.exports = { legacyHandler };
'''.strip(), encoding="utf-8")

    (repo_dir / "package.json").write_text('{"name": "eval-jsts-repo", "version": "1.0.0"}', encoding="utf-8")
    return repo_dir


def create_mixed_fixture(base_dir: Path) -> Path:
    """Create a repository containing both Python backend and TS frontend."""
    repo_dir = base_dir / "eval_mixed_repo"
    (repo_dir / "backend").mkdir(parents=True, exist_ok=True)
    (repo_dir / "frontend").mkdir(parents=True, exist_ok=True)

    (repo_dir / "backend" / "auth.py").write_text('''
def verify_token(token: str) -> bool:
    return len(token) > 10

def handle_login(token: str) -> dict:
    if verify_token(token):
        return {"status": "authorized"}
    return {"status": "unauthorized"}
'''.strip(), encoding="utf-8")

    (repo_dir / "frontend" / "authClient.ts").write_text('''
export function verifyToken(token: string): boolean {
    return token.startsWith("bearer_");
}

export function loginClient(token: string): boolean {
    return verifyToken(token);
}
'''.strip(), encoding="utf-8")

    return repo_dir


def create_malformed_fixture(base_dir: Path) -> Path:
    """Create a repository containing both valid and corrupt source files."""
    repo_dir = base_dir / "eval_malformed_repo"
    repo_dir.mkdir(parents=True, exist_ok=True)

    (repo_dir / "valid.py").write_text('''
def compute_total(a: int, b: int) -> int:
    return a + b
'''.strip(), encoding="utf-8")

    (repo_dir / "valid.ts").write_text('''
export function calculateTax(amount: number): number {
    return amount * 0.1;
}
'''.strip(), encoding="utf-8")

    (repo_dir / "corrupted_syntax.ts").write_text('''
export function broken( {{ [[[ <<< syntax error unclosed
'''.strip(), encoding="utf-8")

    (repo_dir / "corrupted_python.py").write_text('''
def invalid_py(
    return None
'''.strip(), encoding="utf-8")

    return repo_dir


def create_isolation_fixtures(base_dir: Path) -> tuple[Path, Path]:
    """Create two distinct repositories with identical function names but different semantics."""
    repo_a = base_dir / "eval_tenant_alpha"
    repo_b = base_dir / "eval_tenant_beta"
    repo_a.mkdir(parents=True, exist_ok=True)
    repo_b.mkdir(parents=True, exist_ok=True)

    (repo_a / "billing.py").write_text('''
def calculate_fee(base: float) -> float:
    """Alpha fee: 5 percent flat."""
    return base * 0.05

def dispatch_invoice(account_id: str, amount: float):
    fee = calculate_fee(amount)
    return {"tenant": "alpha", "fee": fee}
'''.strip(), encoding="utf-8")

    (repo_b / "billing.py").write_text('''
def calculate_fee(base: float) -> float:
    """Beta fee: 20 percent enterprise tier."""
    return base * 0.20

def generate_report(account_id: str, amount: float):
    fee = calculate_fee(amount)
    return {"tenant": "beta", "fee": fee}
'''.strip(), encoding="utf-8")

    return repo_a, repo_b


def create_all_fixtures(base_dir: Path) -> dict[str, Any]:
    """Create all standard evaluation fixtures under base_dir."""
    py_repo = create_python_fixture(base_dir)
    jsts_repo = create_jsts_fixture(base_dir)
    mixed_repo = create_mixed_fixture(base_dir)
    mal_repo = create_malformed_fixture(base_dir)
    repo_a, repo_b = create_isolation_fixtures(base_dir)
    return {
        "python": py_repo,
        "jsts": jsts_repo,
        "mixed": mixed_repo,
        "malformed": mal_repo,
        "tenant_a": repo_a,
        "tenant_b": repo_b,
        "isolation": (repo_a, repo_b),
    }
