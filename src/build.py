#!/usr/bin/env python3
"""Build a libc-free AArch64 Linux ELF from one relocation-free text section."""
import hashlib, pathlib, struct, subprocess
root=pathlib.Path(__file__).resolve().parent
out=root.parent/'dist'; out.mkdir(exist_ok=True)
obj=out/'entry-v3.o'
subprocess.run(['clang','--target=aarch64-linux-gnu','-c','entry.S','-o',str(obj)],cwd=root,check=True)
b=obj.read_bytes()
h=struct.unpack_from('<16sHHIQQQIHHHHHH',b)
assert h[1:4]==(1,183,1)
sections=[struct.unpack_from('<IIQQQQIIQQ',b,h[6]+i*h[11]) for i in range(h[12])]
assert not any(s[1] in (4,9) and s[5] for s in sections), 'relocations not permitted'
strings=sections[h[13]]; names=b[strings[4]:strings[4]+strings[5]]
text=next(s for s in sections if names[s[0]:].split(b'\0',1)[0]==b'.text')
code=b[text[4]:text[4]+text[5]]
base=0x400000; offset=0x1000; size=offset+len(code)
ident=b'\x7fELF\x02\x01\x01'+bytes(9)
header=struct.pack('<16sHHIQQQIHHHHHH',ident,2,183,1,base+offset,64,0,0,64,56,2,0,0,0)
load=struct.pack('<IIQQQQQQ',1,5,0,base,base,size,size,0x1000)
stack=struct.pack('<IIQQQQQQ',0x6474e551,6,0,0,0,0,0,16)
blob=(header+load+stack).ljust(offset,b'\0')+code
p=out/'flashpilot-dfd4b419-installer-v3'; p.write_bytes(blob); p.chmod(0o755)
assert (root/'install.sh').read_bytes()+b'\0' in blob
print(hashlib.sha256(blob).hexdigest(),p.name)
