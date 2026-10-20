import os
import shutil
import tempfile
import time
from pathlib import Path

from ingestion.chunker import chunk_js_ts_file, chunk_python_file, chunk_text_file
from ingestion.repo_walker import chunk_repo
from ingestion.graph_builder import (
    build_graph,
    callers_of,
    callees_of,
    blast_radius,
    _find_matches,
)
from ingestion.hybrid_search import HybridIndex


def create_js_ts_repo():
    temp_dir = Path(tempfile.mkdtemp(prefix="reposage_js_ts_test_"))
    (temp_dir / "src").mkdir(parents=True, exist_ok=True)
    (temp_dir / "src" / "components").mkdir(parents=True, exist_ok=True)
    (temp_dir / "src" / "services").mkdir(parents=True, exist_ok=True)

    # 1. Utils module (TypeScript)
    (temp_dir / "src" / "utils.ts").write_text(
        '''
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
''',
        encoding="utf-8",
    )

    # 2. Services module (TypeScript class & methods)
    (temp_dir / "src" / "services" / "payment.ts").write_text(
        '''
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
''',
        encoding="utf-8",
    )

    # 3. Component module (TSX React component)
    (temp_dir / "src" / "components" / "PaymentButton.tsx").write_text(
        '''
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
''',
        encoding="utf-8",
    )

    # 4. Entrypoint index.ts
    (temp_dir / "src" / "index.ts").write_text(
        '''
import { PaymentButton } from "./components/PaymentButton";
import PaymentService from "./services/payment";

export function initializeApp() {
    const s = new PaymentService("init");
    return PaymentButton;
}
''',
        encoding="utf-8",
    )

    # 5. CommonJS module (JavaScript)
    (temp_dir / "src" / "legacy.js").write_text(
        '''
const { validateAmount } = require("./utils");

function legacyHandler(amt) {
    return validateAmount(amt);
}

module.exports = { legacyHandler };
''',
        encoding="utf-8",
    )

    return temp_dir


def create_mixed_repo(js_ts_dir: Path) -> Path:
    (js_ts_dir / "backend").mkdir(parents=True, exist_ok=True)
    (js_ts_dir / "backend" / "server.py").write_text(
        '''
from backend.py_utils import verify_token

class ServerApp:
    def handle_request(self, token: str):
        self.log_request()
        return verify_token(token)

    def log_request(self):
        pass
''',
        encoding="utf-8",
    )
    (js_ts_dir / "backend" / "py_utils.py").write_text(
        '''
def verify_token(token: str) -> bool:
    return len(token) > 0
''',
        encoding="utf-8",
    )
    return js_ts_dir


def test_js_ts_chunking(js_ts_repo):
    utils_file = str(js_ts_repo / "src" / "utils.ts")
    chunks = chunk_js_ts_file(utils_file)

    chunk_names = [c.name for c in chunks]
    assert "ValidationResult" in chunk_names
    assert "validateAmount" in chunk_names
    assert "formatCurrency" in chunk_names

    # Check start and end lines
    for c in chunks:
        assert c.start_line > 0
        assert c.end_line >= c.start_line
        assert c.file_path == utils_file


def test_js_ts_class_methods(js_ts_repo):
    svc_file = str(js_ts_repo / "src" / "services" / "payment.ts")
    chunks = chunk_js_ts_file(svc_file)

    class_chunks = [c for c in chunks if c.chunk_type == "class"]
    method_chunks = [c for c in chunks if c.chunk_type == "method"]

    assert any(c.name == "PaymentService" for c in class_chunks)
    method_names = [m.name for m in method_chunks]
    assert "constructor" in method_names
    assert "processPayment" in method_names
    assert "logTransaction" in method_names

    process_payment_chunk = next(m for m in method_chunks if m.name == "processPayment")
    assert process_payment_chunk.parent_class == "PaymentService"
    assert "this.logTransaction" in process_payment_chunk.calls
    assert "validateAmount" in process_payment_chunk.calls


def test_tsx_component_extraction(js_ts_repo):
    btn_file = str(js_ts_repo / "src" / "components" / "PaymentButton.tsx")
    chunks = chunk_js_ts_file(btn_file)

    names = [c.name for c in chunks]
    assert "PaymentButton" in names
    assert "ButtonProps" in names


def test_js_ts_dependency_graph(js_ts_repo):
    chunks, stats = chunk_repo(str(js_ts_repo), verbose=False, return_stats=True)
    assert stats["files_discovered"] >= 5
    assert stats["files_skipped"] == 0

    graph = build_graph(chunks, repo_path=str(js_ts_repo))

    # Test direct callers
    val_callers = callers_of(graph, "validateAmount")
    assert any("services/payment.ts::PaymentService.processPayment" in c for c in val_callers)
    assert any("legacy.js::legacyHandler" in c for c in val_callers)

    # Test direct callees
    proc_callees = callees_of(graph, "PaymentService.processPayment")
    assert any("utils.ts::validateAmount" in c for c in proc_callees)
    assert any("services/payment.ts::PaymentService.logTransaction" in c for c in proc_callees)

    # Test blast radius (transitive reverse callers)
    blast = blast_radius(graph, "validateAmount", max_depth=2)
    # processPayment and legacyHandler are depth 1
    assert any("services/payment.ts::PaymentService.processPayment" in k and v == 1 for k, v in blast.items())
    assert any("legacy.js::legacyHandler" in k and v == 1 for k, v in blast.items())
    # PaymentButton and initializeApp are depth 2
    assert any("components/PaymentButton.tsx::PaymentButton" in k and v == 2 for k, v in blast.items())


def test_mixed_language_repo(mixed_repo):
    chunks, stats = chunk_repo(str(mixed_repo), verbose=False, return_stats=True)
    graph = build_graph(chunks, repo_path=str(mixed_repo))

    # Python graph assertions
    py_callers = callers_of(graph, "verify_token")
    assert any("backend/server.py::ServerApp.handle_request" in c for c in py_callers)

    py_callees = callees_of(graph, "ServerApp.handle_request")
    assert any("backend/py_utils.py::verify_token" in c for c in py_callees)
    assert any("backend/server.py::ServerApp.log_request" in c for c in py_callees)

    # JS/TS graph assertions
    js_callers = callers_of(graph, "validateAmount")
    assert any("services/payment.ts::PaymentService.processPayment" in c for c in js_callers)

    # Ensure no false cross-language edges
    for py_c in py_callers:
        assert not py_c.endswith(".ts") and not py_c.endswith(".js")
    for js_c in js_callers:
        assert not js_c.endswith(".py")


def test_malformed_js_ts_error_handling():
    temp_dir = Path(tempfile.mkdtemp(prefix="reposage_malformed_test_"))
    try:
        # Valid file
        (temp_dir / "valid.ts").write_text("export function validFunc() { return 42; }", encoding="utf-8")
        # Broken/malformed file with unclosed tags and invalid syntax
        (temp_dir / "broken.ts").write_text("export function brokenFunc( {{{ invalid syntax @@@ ///", encoding="utf-8")

        chunks, stats = chunk_repo(str(temp_dir), verbose=False, return_stats=True)
        # Ingestion must not crash
        assert len(chunks) >= 2
        # Graph should still index the valid function
        graph = build_graph(chunks, repo_path=str(temp_dir))
        assert any("validFunc" in n for n in graph.nodes)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_hybrid_search_js_ts(js_ts_repo):
    chunks = chunk_repo(str(js_ts_repo), verbose=False)
    index = HybridIndex(chunks, repo_id="test_js_ts_repo", repo_path=str(js_ts_repo))

    # BM25 test
    hits = index.bm25_search("validateAmount", top_k=5)
    assert any("validateAmount" in h for h in hits)

    # Call graph search directly
    callers = callers_of(index.graph, "validateAmount")
    assert len(callers) >= 2
