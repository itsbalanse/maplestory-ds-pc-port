// Print what Ghidra has at the addresses given as args (hex), and try to make functions there.
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.disassemble.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.lang.*;
import java.math.BigInteger;
public class Probe extends GhidraScript {
    public void run() throws Exception {
        Register tmode = currentProgram.getRegister("TMode");
        for (String s : getScriptArgs()) {
            boolean make = s.startsWith("+");
            Address a = toAddr(Long.parseLong(s.replace("+", ""), 16));
            println("== " + a + " insn=" + getInstructionAt(a) + " containing=" + getInstructionContaining(a)
                + " data=" + getDataContaining(a) + " fn=" + getFunctionContaining(a)
                + " bytes=" + String.format("%08x", getInt(a)));
            if (make) {
                Data d = getDataContaining(a);
                if (d != null) removeData(d);
                currentProgram.getProgramContext().setValue(tmode, a, a, BigInteger.ONE);
                DisassembleCommand cmd = new DisassembleCommand(a, null, true);
                boolean ok = cmd.applyTo(currentProgram, monitor);
                println("   disasm ok=" + ok + " msg=" + cmd.getStatusMsg() + " insn=" + getInstructionAt(a));
                println("   fn=" + createFunction(a, null));
            }
        }
    }
}
