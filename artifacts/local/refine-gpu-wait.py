from pathlib import Path
p=Path('scripts/local-research.py');s=p.read_text();i=s.index('@contextmanager');s=s[:i]+'''def gpu_available():
    memory = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        capture_output=True, text=True, check=True,
    )
    used = [int(x.strip()) for x in memory.stdout.splitlines() if x.strip()]
    if not used or any(n > 512 for n in used):
        return False
    applications = subprocess.run(
        ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader,nounits"],
        capture_output=True, text=True, check=True,
    )
    # A model can have a small allocation while starting. Memory alone is not
    # proof that another project's GPU job has finished.
    return not applications.stdout.strip()


def wait_for_gpu(seconds=0):
    if seconds < 0:
        raise ValueError("GPU wait must be nonnegative")
    deadline = time.monotonic() + seconds
    while not gpu_available():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("GPU already in use; wait expired; other workloads unchanged")
        print("Waiting for GPU; other workloads unchanged", flush=True)
        time.sleep(min(30, remaining))


'''+s[i:]
s=s.replace('def runtime(thinking=False, model="qwen3.5:9b", go_template=None):','def runtime(thinking=False, model="qwen3.5:9b", go_template=None, wait_gpu_seconds=0):')
a=s.index('    result = subprocess.run(',s.index('def runtime'));b=s.index('    # Bind probe',a);s=s[:a]+'    wait_for_gpu(wait_gpu_seconds)\n'+s[b:]
s=s.replace('    parser.add_argument("--model", default="qwen3:8b")','    parser.add_argument("--model", default="qwen3:8b")\n    parser.add_argument("--wait-gpu-seconds", type=int, default=0)')
s=s.replace('with runtime(thinking=args.thinking, model=args.model) as client:', 'with runtime(thinking=args.thinking, model=args.model, wait_gpu_seconds=args.wait_gpu_seconds) as client:');p.write_text(s)
for filename,alias in [('local-coverage.py','module'),('local-questions.py','runtime'),('local-filings.py','runtime')]:
 p=Path('scripts')/filename;s=p.read_text();a=s.index('        deadline = time.monotonic()');b=s.index('        with '+alias+'.runtime(',a);s=s[:a]+s[b:];needle='thinking=args.thinking, model=args.model, go_template=False' if filename=='local-coverage.py' else 'thinking=True, model=args.model, go_template=False';s=s.replace(needle,needle+', wait_gpu_seconds=args.wait_gpu_seconds');
 # Their former GPU loops were the sole uses of time/subprocess.
 for name in ['time','subprocess']:
  if name+'.' not in s:s=s.replace('import '+name+'\n','')
 p.write_text(s)
p=Path('scripts/run-local.py');s=p.read_text();s=s.replace('    args = parser.parse_args()', '    parser.add_argument("--wait-gpu-seconds", type=int, default=600, help="Maximum wait for each local GPU stage; other projects are never stopped")\n    args = parser.parse_args()\n    if args.wait_gpu_seconds < 0:\n        parser.error("--wait-gpu-seconds must be nonnegative")');s=s.replace('    run_id = ', '    gpu_wait = ["--wait-gpu-seconds", str(args.wait_gpu_seconds)]\n    run_id = ')
s=s.replace('[sys.executable, "scripts/local-research.py"]','[sys.executable, "scripts/local-research.py"] + gpu_wait').replace('[sys.executable, "scripts/local-coverage.py", "--resume"]','[sys.executable, "scripts/local-coverage.py", "--resume"] + gpu_wait').replace('[sys.executable, "scripts/local-questions.py", "--resume"],','[sys.executable, "scripts/local-questions.py", "--resume"] + gpu_wait,').replace('[sys.executable, "scripts/local-filings.py", "--resume"],','[sys.executable, "scripts/local-filings.py", "--resume"] + gpu_wait,');p.write_text(s)
