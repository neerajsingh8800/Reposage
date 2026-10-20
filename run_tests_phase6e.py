import os
import shutil
import tempfile
from pathlib import Path

from tests import test_phase6e_js_ts as t

def run_all():
    print("=== Running Phase 6E JS/TS Code Intelligence Test Suite ===")

    temp_dir = Path(tempfile.mkdtemp(prefix="reposage_test_runner_"))
    try:
        (temp_dir / "src").mkdir(parents=True, exist_ok=True)
        (temp_dir / "src" / "components").mkdir(parents=True, exist_ok=True)
        (temp_dir / "src" / "services").mkdir(parents=True, exist_ok=True)

        (temp_dir / "src" / "utils.ts").write_text('''
export interface ValidationResult {
    isValid: boolean;
    reason?: string;
}

export function validateAmount(amount: number): ValidationResult {
    if (amount <= 0) {
        return { isValid: false, reason: "Amount must be positive" };
    }
    return { isValid: true };
}

export const formatCurrency = (amount: number, currency: string = "USD"): string => {
    return `${currency} ${amount.toFixed(2)}`;
};
''', encoding="utf-8")

        (temp_dir / "src" / "services" / "payment.ts").write_text('''
import { validateAmount, formatCurrency } from "../utils";

export class PaymentService {
    private apiKey: string;

    constructor(apiKey: string) {
        this.apiKey = apiKey;
    }

    public processPayment(amount: number): boolean {
        this.logTransaction(amount);
        const val = validateAmount(amount);
        if (!val.isValid) {
            return false;
        }
        return true;
    }

    private logTransaction(amount: number): void {
        const str = formatCurrency(amount);
    }
}

export default PaymentService;
''', encoding="utf-8")

        (temp_dir / "src" / "components" / "PaymentButton.tsx").write_text('''
import React from "react";
import PaymentService from "../services/payment";

export interface ButtonProps {
    amount: number;
    onSuccess: () => void;
}

export const PaymentButton: React.FC<ButtonProps> = ({ amount, onSuccess }) => {
    const handlePay = () => {
        const service = new PaymentService("key_123");
        const ok = service.processPayment(amount);
        if (ok) {
            onSuccess();
        }
    };

    return (
        <button className="pay-btn" onClick={handlePay}>
            Pay
        </button>
    );
};
''', encoding="utf-8")

        (temp_dir / "src" / "index.ts").write_text('''
import { PaymentButton } from "./components/PaymentButton";
import PaymentService from "./services/payment";

export function initializeApp() {
    const s = new PaymentService("init");
    return PaymentButton;
}
''', encoding="utf-8")

        (temp_dir / "src" / "legacy.js").write_text('''
const { validateAmount } = require("./utils");

function legacyHandler(amt) {
    return validateAmount(amt);
}

module.exports = { legacyHandler };
''', encoding="utf-8")

        t.test_js_ts_chunking(temp_dir)
        print("  [PASS] test_js_ts_chunking")

        t.test_js_ts_class_methods(temp_dir)
        print("  [PASS] test_js_ts_class_methods")

        t.test_tsx_component_extraction(temp_dir)
        print("  [PASS] test_tsx_component_extraction")

        t.test_js_ts_dependency_graph(temp_dir)
        print("  [PASS] test_js_ts_dependency_graph")

        t.test_malformed_js_ts_error_handling()
        print("  [PASS] test_malformed_js_ts_error_handling")

        t.test_hybrid_search_js_ts(temp_dir)
        print("  [PASS] test_hybrid_search_js_ts")

        # Mixed repo test
        (temp_dir / "backend").mkdir(parents=True, exist_ok=True)
        (temp_dir / "backend" / "server.py").write_text('''
from backend.py_utils import verify_token

class ServerApp:
    def handle_request(self, token: str):
        self.log_request()
        return verify_token(token)

    def log_request(self):
        pass
''', encoding="utf-8")
        (temp_dir / "backend" / "py_utils.py").write_text('''
def verify_token(token: str) -> bool:
    return len(token) > 0
''', encoding="utf-8")

        t.test_mixed_language_repo(temp_dir)
        print("  [PASS] test_mixed_language_repo")

        print("\n>>> ALL PHASE 6E TESTS PASSED SUCCESSFULLY! <<<")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

if __name__ == "__main__":
    run_all()
