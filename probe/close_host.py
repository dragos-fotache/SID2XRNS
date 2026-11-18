#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Normally close only a PID running this project's private Renoise profile."""
import ctypes as C
import json
from pathlib import Path
import time
from host import WORK, call


def close():
    process = json.loads((WORK / 'process.json').read_text())
    pid = process['pid']
    env = Path(f'/proc/{pid}/environ').read_bytes().split(b'\0')
    assert ('XDG_CONFIG_HOME=' + process['profile']).encode() in env
    state = call('inspect')
    assert state['pid'] == pid and Path(state['file']).parent == WORK
    call('stop')
    call('save', name=f"before-close-{process['label']}.xrns")
    x = C.CDLL('libX11.so.6')
    U, I, P = C.c_ulong, C.c_int, C.c_void_p
    x.XOpenDisplay.restype=P
    d=x.XOpenDisplay(None);assert d
    x.XDefaultRootWindow.argtypes=[P];x.XDefaultRootWindow.restype=U
    x.XInternAtom.argtypes=[P,C.c_char_p,I];x.XInternAtom.restype=U
    x.XQueryTree.argtypes=[P,U,C.POINTER(U),C.POINTER(U),C.POINTER(C.POINTER(U)),C.POINTER(C.c_uint)]
    x.XGetWindowProperty.argtypes=[P,U,U,C.c_long,C.c_long,I,U,C.POINTER(U),C.POINTER(I),C.POINTER(U),C.POINTER(U),C.POINTER(C.POINTER(C.c_ubyte))]
    x.XFree.argtypes=[P];x.XFetchName.argtypes=[P,U,C.POINTER(C.c_char_p)]
    windows=[]
    def walk(w):
        typ,fmt,n,left,data=U(),I(),U(),U(),C.POINTER(C.c_ubyte)()
        x.XGetWindowProperty(d,w,x.XInternAtom(d,b'_NET_WM_PID',0),0,1,0,6,C.byref(typ),C.byref(fmt),C.byref(n),C.byref(left),C.byref(data))
        owner=C.cast(data,C.POINTER(U))[0] if n.value else 0
        if data:x.XFree(data)
        name=C.c_char_p();x.XFetchName(d,w,C.byref(name))
        title=name.value.decode(errors='replace') if name.value else ''
        if title and owner==pid and (title=='Renoise (x86_64)' or title.endswith(' - Renoise (x86_64)')):windows.append(w)
        if name:x.XFree(name)
        root,parent,children,count=U(),U(),C.POINTER(U)(),C.c_uint()
        if x.XQueryTree(d,w,C.byref(root),C.byref(parent),C.byref(children),C.byref(count)):
            for i in range(count.value):walk(children[i])
            if children:x.XFree(children)
    walk(x.XDefaultRootWindow(d));assert len(windows)==1,windows
    class Data(C.Union):_fields_=[('b',C.c_char*20),('l',C.c_long*5)]
    class Message(C.Structure):_fields_=[('type',I),('serial',U),('send_event',I),('display',P),('window',U),('message_type',U),('format',I),('data',Data)]
    class Event(C.Union):_fields_=[('message',Message),('pad',C.c_long*24)]
    event=Event();event.message=Message(33,0,1,d,windows[0],x.XInternAtom(d,b'WM_PROTOCOLS',0),32,Data())
    event.message.data.l[0]=x.XInternAtom(d,b'WM_DELETE_WINDOW',0)
    x.XSendEvent.argtypes=[P,U,I,C.c_long,C.POINTER(Event)]
    x.XFlush.argtypes=[P]
    assert x.XSendEvent(d,windows[0],0,0,C.byref(event));x.XFlush(d)
    for _ in range(100):
        path=Path(f'/proc/{pid}/stat')
        if not path.exists() or path.read_text().split(')')[1].split()[0]=='Z':
            print(json.dumps({'pid':pid,'normal_close':True}));return
        time.sleep(.2)
    raise RuntimeError('Private host did not close; no force was used')


if __name__=='__main__':close()
