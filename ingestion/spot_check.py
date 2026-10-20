"""Quick spot-check: print the actual chunks found in one real file,
so we can eyeball whether property decorators / class hierarchies
were parsed correctly, not just that nothing crashed.
"""
import sys
from ingestion.chunker import chunk_python_file

from pathlib import Path

target = sys.argv[1] if len(sys.argv) > 1 else (
    "sample_repo/payments.py" if Path("sample_repo/payments.py").exists() else "../sample_repo/payments.py"
)
chunks = chunk_python_file(target)

print(f"\n{len(chunks)} chunks in {target}\n" + "=" * 60)
for c in chunks:
    label = f"[{c.chunk_type.upper()}] {c.name}"
    if c.parent_class:
        label += f"  (method of {c.parent_class})"
    print(f"{label}  — lines {c.start_line}-{c.end_line}")
