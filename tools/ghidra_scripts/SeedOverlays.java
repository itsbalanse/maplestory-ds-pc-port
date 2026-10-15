// Find functions inside overlay blocks (nothing in static code references them directly).
// Seeds: ARM `push {..., lr}` / Thumb `push {..., lr}` prologues, code pointers stored in the
// overlay's own data (vtables, sinit tables), and extra addresses listed in env MSDS_SEEDS
// (lines: "<hex addr> <space or 'ram'> <thumb 0/1>"), then re-runs auto-analysis.
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.disassemble.*;
import ghidra.program.model.address.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.lang.*;
import ghidra.program.model.listing.*;
import java.math.BigInteger;
import java.nio.file.*;
import java.util.*;

public class SeedOverlays extends GhidraScript {
    Register tmode;
    int created = 0;

    void seed(Address a, boolean thumb) throws Exception {
        if (getFunctionAt(a) != null) return;
        if (getInstructionAt(a) != null && getFunctionContaining(a) != null) return;
        try {
            currentProgram.getProgramContext().setValue(tmode, a, a, BigInteger.valueOf(thumb ? 1 : 0));
        } catch (Exception e) { return; }
        DisassembleCommand cmd = new DisassembleCommand(a, null, true);
        if (!cmd.applyTo(currentProgram, monitor)) return;
        if (getInstructionAt(a) == null) return;
        if (createFunction(a, null) != null) created++;
    }

    public void run() throws Exception {
        tmode = currentProgram.getRegister("TMode");
        Memory mem = currentProgram.getMemory();
        String seedFile = System.getenv("MSDS_SEEDS");
        for (MemoryBlock b : mem.getBlocks()) {
            if (!b.isOverlay()) continue;
            Address s = b.getStart();
            long len = b.getSize();
            long lo = s.getOffset(), hi = lo + len;
            byte[] data = new byte[(int) len];
            b.getBytes(s, data);
            // code pointers in the overlay itself
            for (int i = 0; i + 4 <= len; i += 4) {
                long w = (data[i] & 0xffL) | (data[i + 1] & 0xffL) << 8 | (data[i + 2] & 0xffL) << 16 | (data[i + 3] & 0xffL) << 24;
                if (w > lo && w < hi) {
                    boolean th = (w & 1) == 1;
                    if (!th && (w & 3) != 0) continue;
                    seed(s.add((w & ~1L) - lo), th);
                }
            }
            // prologues
            for (int i = 0; i + 4 <= len; i += 4) {
                int w = (data[i] & 0xff) | (data[i + 1] & 0xff) << 8 | (data[i + 2] & 0xff) << 16 | (data[i + 3] & 0xff) << 24;
                if ((w & 0xFFFF4000) == 0xE92D4000) seed(s.add(i), false);
            }
            for (int i = 0; i + 2 <= len; i += 2) {
                int h = (data[i] & 0xff) | (data[i + 1] & 0xff) << 8;
                if ((h & 0xFF00) == 0xB500) {
                    Address a = s.add(i);
                    if (getInstructionContaining(a) == null) seed(a, true);
                }
            }
        }
        if (seedFile != null && Files.exists(Paths.get(seedFile))) {
            for (String line : Files.readAllLines(Paths.get(seedFile))) {
                String[] p = line.trim().split("\\s+");
                if (p.length < 3) continue;
                long addr = Long.parseLong(p[0], 16);
                AddressSpace sp = currentProgram.getAddressFactory().getAddressSpace(p[1]);
                if (sp == null) continue;
                seed(sp.getAddress(addr), p[2].equals("1"));
            }
        }
        println("seeded functions: " + created);
        analyzeAll(currentProgram);
        println("functions now: " + currentProgram.getFunctionManager().getFunctionCount());
    }
}
