// Post-import setup: add DS memory regions/overlay info if needed, mark entry.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
public class Setup extends GhidraScript {
    public void run() throws Exception {
        Address e = toAddr(0x02000800);
        disassemble(e);
        createFunction(e, "_start");
    }
}
