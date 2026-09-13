import re, subprocess
REV, REPO = "upstream/master", "/Users/jonhillesheim/forge/tock"
def show(p):
    return subprocess.run(["git","show",f"{REV}:{p}"],capture_output=True,text=True,cwd=REPO).stdout

files = subprocess.run(["git","grep","-ln","fn transmit_buffer",REV,"--","chips/"],
                       capture_output=True,text=True,cwd=REPO).stdout.split()
files = sorted(f.split(":",1)[1] for f in files if ":" in f)

# The contract: when the client callback is made, the UART must already be
# ready for another call. The bug shape is a state reset AFTER the callback.
STATE_RESET = re.compile(r"(state|status)\w*\.set\([^)]*(Idle|Ready|None)", re.I)
CALLBACK    = re.compile(r"\.(received_buffer|transmitted_buffer)\s*\(")

print("  driver                                cb-line  reset-after-cb?")
for p in files:
    src = show(p).split("\n")
    for i, line in enumerate(src):
        if not CALLBACK.search(line):
            continue
        if "fn " in line:          # the trait definition, not a call
            continue
        # look ahead inside the same block for a state reset
        after = "\n".join(src[i+1 : i+10])
        before = "\n".join(src[max(0, i-10) : i])
        r_after = bool(STATE_RESET.search(after))
        r_before = bool(STATE_RESET.search(before))
        if r_after and not r_before:
            print(f"    {p:38} {i+1:>6}   RESET AFTER CALLBACK")
