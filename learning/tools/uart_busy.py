import re, subprocess, sys
sys.path.insert(0, "/private/tmp/claude-501/-Users-jonhillesheim-forge-tock/a4370ed3-7c74-4abb-9ad7-b7c73c0a87ba/scratchpad")
REV, REPO = "upstream/master", "/Users/jonhillesheim/forge/tock"
def show(p):
    return subprocess.run(["git","show",f"{REV}:{p}"],capture_output=True,text=True,cwd=REPO).stdout
def find_fn(src, fname):
    out=[]
    for m in re.finditer(r"\bfn\s+"+re.escape(fname)+r"\s*\(", src):
        b=src.find("{", m.end())
        if b<0: continue
        d,k=0,b
        while k<len(src):
            if src[k]=="{": d+=1
            elif src[k]=="}":
                d-=1
                if d==0: break
            k+=1
        out.append((src[:m.start()].count("\n")+1, src[b:k+1]))
    return out
def body_all(src, fname):
    """the fn plus any single-hop helpers it names"""
    res=[]
    for line, body in find_fn(src, fname):
        txt=body
        for hm in re.finditer(r"self\.(\w+)\(", body):
            for _l,hb in find_fn(src, hm.group(1)):
                txt+=hb
        res.append((line,txt))
    return res
files=subprocess.run(["git","grep","-ln","fn transmit_buffer",REV,"--","chips/","capsules/"],
                     capture_output=True,text=True,cwd=REPO).stdout.split()
files=sorted(f.split(":",1)[1] for f in files if ":" in f)
for fname,label in (("transmit_buffer","TX"),("receive_buffer","RX")):
    print(f"\n===== {label}: Err(BUSY) when an operation is already outstanding =====")
    miss=[]
    n=0
    for p in files:
        src=show(p)
        for line, txt in body_all(src, fname):
            n+=1
            if not re.search(r"ErrorCode::BUSY", txt):
                miss.append((p,line))
    print(f"  implementations: {n}")
    print(f"  NO BUSY path:    {len(miss)}")
    for p,l in miss: print(f"    {p}:{l}")
