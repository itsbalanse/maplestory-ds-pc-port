// Recover Thumb switch tables Ghidra missed (found by tools/find_switch_tables.py): disassemble each
// case target, add a computed-jump reference from the `add pc,rN` to it, and grow the function body
// so the recompiler emits the case blocks. Input: env MSDS_SWITCH, lines "<space> <target> <site>".
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.disassemble.*;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.program.model.address.*;
import ghidra.program.model.lang.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.math.BigInteger;
import java.nio.file.*;
import java.util.*;

public class SeedSwitchTargets extends GhidraScript {
    public void run() throws Exception {
        Register tmode = currentProgram.getRegister("TMode");
        String file = System.getenv("MSDS_SWITCH");
        if (file == null || !Files.exists(Paths.get(file))) { println("no MSDS_SWITCH file"); return; }
        Set<Function> touched = new LinkedHashSet<>();
        int done = 0;
        for (String line : Files.readAllLines(Paths.get(file))) {
            String[] p = line.trim().split("\\s+");
            if (p.length < 3) continue;
            AddressSpace sp = currentProgram.getAddressFactory().getAddressSpace(p[0]);
            if (sp == null) { println("unknown space " + p[0]); continue; }
            Address tgt = sp.getAddress(Long.parseLong(p[1], 16));
            Address site = sp.getAddress(Long.parseLong(p[2], 16));
            Instruction jmp = getInstructionAt(site);
            Function fn = getFunctionContaining(site);
            if (jmp == null || fn == null) { println("no instruction/function at " + site); continue; }
            if (getInstructionAt(tgt) == null) {
                Data d = getDataContaining(tgt);
                if (d != null && d.isDefined()) removeData(d);
                if (getInstructionContaining(tgt) != null) { println("target inside another instruction: " + tgt); continue; }
                currentProgram.getProgramContext().setValue(tmode, tgt, tgt, BigInteger.ONE);
                new DisassembleCommand(tgt, null, true).applyTo(currentProgram, monitor);
            }
            if (getInstructionAt(tgt) == null) { println("could not disassemble " + tgt); continue; }
            jmp.addMnemonicReference(tgt, RefType.COMPUTED_JUMP, SourceType.USER_DEFINED);
            touched.add(fn);
            done++;
        }
        for (Function fn : touched) CreateFunctionCmd.fixupFunctionBody(currentProgram, fn, monitor);
        // functions called only from the recovered case blocks were never created either
        int callees = 0;
        for (Function fn : touched) {
            for (Instruction ins : currentProgram.getListing().getInstructions(fn.getBody(), true)) {
                if (!ins.getFlowType().isCall()) continue;
                for (Address t : ins.getFlows()) {
                    if (getFunctionAt(t) != null) continue;
                    if (getInstructionAt(t) == null) new DisassembleCommand(t, null, true).applyTo(currentProgram, monitor);
                    if (getInstructionAt(t) != null && createFunction(t, null) != null) callees++;
                }
            }
        }
        println("switch targets recovered: " + done + " in " + touched.size() + " functions; new callees: " + callees);
    }
}
