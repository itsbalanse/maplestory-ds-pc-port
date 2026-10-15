// Overlay functions reached only through pointers stored in the static ARM9 binary (callback
// tables, vtables) are invisible to analysis of the overlay itself. Scan static data for words
// pointing into overlay slots and, in every overlay block covering that address, create a function
// there when the bytes look like a function start (Thumb push {..,lr} / ARM stmdb sp!,{..,lr}).
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.disassemble.*;
import ghidra.program.model.address.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.lang.*;
import ghidra.program.model.listing.*;
import java.math.BigInteger;
import java.util.*;

public class SeedOverlayPointers extends GhidraScript {
    public void run() throws Exception {
        Register tmode = currentProgram.getRegister("TMode");
        Memory mem = currentProgram.getMemory();
        List<MemoryBlock> ovs = new ArrayList<>();
        for (MemoryBlock b : mem.getBlocks()) if (b.isOverlay()) ovs.add(b);
        Set<Long> targets = new TreeSet<>();
        long[][] ranges = {{0x02000000L, 0x0214e818L}};
        for (long[] r : ranges)
            for (long p = r[0]; p + 4 <= r[1]; p += 4) {
                long w = mem.getInt(toAddr(p)) & 0xffffffffL;
                if (w >= 0x02162d40L && w < 0x02172000L) targets.add(w);
            }
        int made = 0, fixedModes = 0;
        for (long w : targets) {
            boolean thumb = (w & 1) == 1;
            long a = w & ~1L;
            if (!thumb && (a & 3) != 0) continue;
            for (MemoryBlock b : ovs) {
                long lo = b.getStart().getOffset(), hi = lo + b.getSize();
                if (a < lo || a + 4 > hi) continue;
                Address ad = b.getStart().add(a - lo);
                int v = mem.getInt(ad);
                boolean ok = thumb ? ((v & 0xFF00) == 0xB500) : ((v & 0xFFFF4000) == 0xE92D4000);
                if (!ok) continue;
                Function existing = getFunctionAt(ad);
                if (existing != null) {
                    BigInteger m = currentProgram.getProgramContext().getValue(tmode, ad, false);
                    boolean isThumb = m != null && m.intValue() == 1;
                    if (isThumb == thumb) continue;
                    // disassembled in the wrong instruction set: rebuild it
                    AddressSetView body = existing.getBody();
                    removeFunction(existing);
                    clearListing(body);
                    fixedModes++;
                }
                if (getInstructionContaining(ad) != null && getInstructionAt(ad) == null) continue;
                Data d = getDataContaining(ad);
                if (d != null && d.isDefined()) removeData(d);
                if (getInstructionAt(ad) == null) {
                    currentProgram.getProgramContext().setValue(tmode, ad, ad, BigInteger.valueOf(thumb ? 1 : 0));
                    new DisassembleCommand(ad, null, true).applyTo(currentProgram, monitor);
                }
                if (getInstructionAt(ad) != null && createFunction(ad, null) != null) made++;
            }
        }
        println("overlay pointer seeds: " + made + ", mode fixes: " + fixedModes + " (from " + targets.size() + " pointers)");
    }
}
