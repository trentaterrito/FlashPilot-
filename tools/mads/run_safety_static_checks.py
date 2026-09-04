"""Run both real MISRA analyzers with installed deps, without uv sync or shell splitting.

This is an environment-safe direct equivalent of the two repositories' cppcheck
invocations, not a waiver, mutation-suite substitute, or compliance certificate.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess


def main():
  import cppcheck
  root = Path(__file__).resolve().parents[2]
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--output", type=Path, required=True)
  args = parser.parse_args()
  args.output = args.output.resolve()
  args.output.mkdir(parents=True, exist_ok=True)
  install = Path(cppcheck.DIR)
  binary = install / "cppcheck"
  version = subprocess.check_output([str(binary), "--version"], text=True).strip()
  table = subprocess.check_output([shutil.which("python3"), str(install / "addons/misra.py"), "-generate-table"])
  results = {"cppcheck": version, "scopes": {}}
  for scope, repo, source, compiler, extra in (
    ("opendbc", root / "opendbc_repo", "opendbc/safety/tests/misra/main.c", "cc", ["--enable=unusedFunction", "-D__has_include_next(x)=0"]),
    ("panda_h7", root / "panda", "board/main.c", "arm-none-eabi-gcc",
     ["--disable=unusedFunction", "-DSTM32H7", "-DSTM32H725xx", "-UCMSIS_NVIC_VIRTUAL", "-UCMSIS_VECTAB_VIRTUAL",
      "-UPANDA_JUNGLE", "-UBOOTSTUB", "-I", str(root / "panda/board/stm32h7/inc"), "--suppress=*:*inc/*"]),
  ):
    misra = repo / ("opendbc/safety/tests/misra" if scope == "opendbc" else "tests/misra")
    include = subprocess.check_output([compiler, "-print-file-name=include"], text=True).strip()
    cmd = [str(binary), "--inline-suppr", "-I", str(repo), "-I", str(root / "opendbc_repo"), "-I", include,
           "--suppress=missingIncludeSystem", "--suppress=*:*include/*", f"--suppressions-list={misra / 'suppressions.txt'}",
           "--error-exitcode=2", "--check-level=exhaustive", "--safety", "--platform=arm32-wchar_t4", "-D__GNUC__=9",
           "--std=c11", "--enable=all", "--addon=misra", f"--checkers-report={args.output / (scope + '.checkers.txt')}",
           *extra, str(repo / source)]
    run = subprocess.run(cmd, cwd=args.output, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    (args.output / (scope + ".log")).write_text(run.stdout)
    violation = any(s in run.stdout for s in ("misra violation", "error:", "style:"))
    table_matches = table == (misra / "coverage_table").read_bytes()
    results["scopes"][scope] = {"command": cmd, "exitCode": run.returncode, "violations": violation,
                               "coverageTableMatches": table_matches,
                               "pass": run.returncode == 0 and not violation and table_matches}
  (args.output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
  print(json.dumps(results, indent=2))
  return 0 if all(s["pass"] for s in results["scopes"].values()) else 1


if __name__ == "__main__":
  raise SystemExit(main())
