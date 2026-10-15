// Linear sweep: in the named blocks, every 4-byte aligned address that is not yet covered by an
// instruction is disassembled as ARM and turned into a function. Used for hand-written assembly
// reached only through computed jumps (the Mobiclip decoder copied into ITCM). Args: block names.
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.disassemble.*;
import ghidra.program.model.address.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.lang.*;
import ghidra.program.model.listing.*;
import java.math.BigInteger;
public class SeedLinear extends GhidraScript {
    public void run() throws Exception {
        Register tmode = currentProgram.getRegister("TMode");
        int made = 0;
        for (String name : getScriptArgs()) {
            MemoryBlock b = currentProgram.getMemory().getBlock(name);
            if (b == null) { println("no block " + name); continue; }
            for (Address a = b.getStart(); a.compareTo(b.getEnd()) < 0; a = a.add(4)) {
                if (getInstructionContaining(a) != null) {
                    if (getFunctionContaining(a) == null && getInstructionAt(a) != null && createFunction(a, null) != null) made++;
                    continue;
                }
                Data d = getDataContaining(a);
                if (d != null && d.isDefined()) removeData(d);
                currentProgram.getProgramContext().setValue(tmode, a, a, BigInteger.ZERO);
                DisassembleCommand cmd = new DisassembleCommand(a, null, true);
                cmd.applyTo(currentProgram, monitor);
                if (getInstructionAt(a) != null && getFunctionContaining(a) == null && createFunction(a, null) != null) made++;
            }
        }
        println("linear sweep functions: " + made);
    }
}
