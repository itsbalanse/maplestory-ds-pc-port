// Seed functions in the always-resident code (static ARM9 + ITCM) from code pointers found in
// data: odd words -> Thumb code, plus ARM prologues in undisassembled gaps. Pointer targets that
// land inside an existing function (but not at its entry) are written to env MSDS_EXTRA_ENTRIES
// so the recompiler can emit secondary entry points.
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.disassemble.*;
import ghidra.program.model.address.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.lang.*;
import ghidra.program.model.listing.*;
import java.io.*;
import java.math.BigInteger;
import java.util.*;

public class SeedStatic extends GhidraScript {
    Register tmode;
    int created = 0;

    boolean seed(Address a, boolean thumb) throws Exception {
        if (getFunctionAt(a) != null) return false;
        if (getInstructionAt(a) != null && getFunctionContaining(a) == null) {
            if (createFunction(a, null) != null) { created++; return true; }
            return false;
        }
        if (getInstructionContaining(a) != null) return false;
        Data d = getDataContaining(a);
        if (d != null && d.isDefined()) {
            if (!thumb) return false;  // only trust odd (Thumb) pointers enough to override data
            removeData(d);
        }
        // something other than undefined bytes can sit here (Ghidra refuses to disassemble it)
        if (thumb) clearListing(a, a.add(1));
        try {
            currentProgram.getProgramContext().setValue(tmode, a, a, BigInteger.valueOf(thumb ? 1 : 0));
        } catch (Exception e) { return false; }
        DisassembleCommand cmd = new DisassembleCommand(a, null, true);
        if (!cmd.applyTo(currentProgram, monitor) || getInstructionAt(a) == null) return false;
        if (createFunction(a, null) != null) { created++; return true; }
        return false;
    }

    public void run() throws Exception {
        tmode = currentProgram.getRegister("TMode");
        Memory mem = currentProgram.getMemory();
        long[][] ranges = {{0x02000000L, 0x0214e240L}, {0x01ff8000L, 0x01ff8000L + 0x500 + 0x1de0}};
        Set<Long> extra = new TreeSet<>();
        for (int pass = 0; pass < 2; pass++) {
            for (long[] r : ranges) {
                for (long p = r[0]; p + 4 <= r[1]; p += 4) {
                    Address pa = toAddr(p);
                    if (!mem.contains(pa)) continue;
                    long w = mem.getInt(pa) & 0xffffffffL;
                    boolean inRange = false;
                    for (long[] t : ranges) if (w >= t[0] && w < t[1]) inRange = true;
                    if (!inRange) continue;
                    if ((w & 1) == 1) {
                        Address ta = toAddr(w & ~1L);
                        Instruction ins = getInstructionAt(ta);
                        if (ins == null && getInstructionContaining(ta) == null) {
                            seed(ta, true);
                        } else if (ins != null && getFunctionAt(ta) == null && getFunctionContaining(ta) != null) {
                            extra.add(w & ~1L);
                        }
                    } else if ((w & 3) == 0 && pass == 1) {
                        Address ta = toAddr(w);
                        // ARM function pointers: only if the target starts with a typical prologue
                        if (getInstructionContaining(ta) == null && mem.contains(ta) && getDataContaining(ta) == null) {
                            int iw = mem.getInt(ta);
                            // unconditional ARM instruction (cond = AL) in an undisassembled, untyped gap
                            if ((iw >>> 28) == 0xE) seed(ta, false);
                        }
                    }
                }
            }
        }
        // ARM prologues in undisassembled gaps of static code
        for (long p = 0x02000000L; p + 4 <= 0x0214e240L; p += 4) {
            Address a = toAddr(p);
            if (getInstructionContaining(a) != null) continue;
            int w = mem.getInt(a);
            if ((w & 0xFFFF4000) == 0xE92D4000) seed(a, false);
        }
        // orphan code: disassembled instructions that belong to no function
        int orphans = 0;
        for (MemoryBlock b : mem.getBlocks()) {
            InstructionIterator it = currentProgram.getListing().getInstructions(b.getStart(), true);
            while (it.hasNext()) {
                Instruction ins = it.next();
                if (!b.contains(ins.getAddress())) break;
                if (getFunctionContaining(ins.getAddress()) == null) {
                    if (createFunction(ins.getAddress(), null) != null) orphans++;
                }
            }
        }
        println("orphan code functions: " + orphans);
        println("static seeds created: " + created + ", mid-function pointer targets: " + extra.size());
        String out = System.getenv("MSDS_EXTRA_ENTRIES");
        if (out != null) {
            try (PrintWriter pw = new PrintWriter(new FileWriter(out))) {
                for (long e : extra) pw.println(Long.toHexString(e));
            }
        }
        analyzeAll(currentProgram);
        println("functions now: " + currentProgram.getFunctionManager().getFunctionCount());
    }
}
