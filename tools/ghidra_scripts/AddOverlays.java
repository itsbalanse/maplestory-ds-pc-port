// Pre-analysis setup for the full MapleStory DS ARM9 program:
//  - ITCM block at 0x01ff8000 (autoload 0 + overlay 0, which lives in ITCM)
//  - DTCM block at 0x027e0000 (autoload 1)
//  - every other overlay as a Ghidra overlay block named ovNNN at its RAM address
//  - entry points: _start, each overlay's static-initializer table targets
// Env MSDS_EXTRACTED points at the extracted/ folder.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.lang.*;
import ghidra.program.model.symbol.*;
import java.io.*;
import java.nio.file.*;
import java.math.BigInteger;

public class AddOverlays extends GhidraScript {
    public void run() throws Exception {
        String ex = System.getenv("MSDS_EXTRACTED");
        Memory mem = currentProgram.getMemory();
        byte[] arm9 = Files.readAllBytes(Paths.get(ex, "arm9_dec.bin"));
        // ITCM: autoload 0 (0x500 bytes from 0x214e240) + overlay 0 at 0x01ff8500
        File ov0 = null;
        File[] ovs = new File(ex, "overlay_dec").listFiles();
        java.util.Arrays.sort(ovs);
        for (File f : ovs) if (f.getName().startsWith("ov000_")) ov0 = f;
        byte[] o0 = Files.readAllBytes(ov0.toPath());
        byte[] itcm = new byte[0x500 + o0.length];
        System.arraycopy(arm9, 0x14e240, itcm, 0, 0x500);
        System.arraycopy(o0, 0, itcm, 0x500, o0.length);
        mem.createInitializedBlock("ITCM", toAddr(0x01ff8000L), new ByteArrayInputStream(itcm), itcm.length, monitor, false);
        byte[] dtcm = new byte[0xc0];
        System.arraycopy(arm9, 0x14e740, dtcm, 0, 0xc0);
        mem.createInitializedBlock("DTCM", toAddr(0x027e0000L), new ByteArrayInputStream(dtcm), dtcm.length, monitor, false);

        Register tmode = currentProgram.getRegister("TMode");
        for (File f : ovs) {
            String n = f.getName();
            if (n.startsWith("ov000_")) continue;
            int id = Integer.parseInt(n.substring(2, 5));
            long ram = Long.parseLong(n.substring(6, 14), 16);
            byte[] data = Files.readAllBytes(f.toPath());
            MemoryBlock b = mem.createInitializedBlock(String.format("ov%03d", id), toAddr(ram), new ByteArrayInputStream(data), data.length, monitor, true);
            println("overlay " + n + " -> " + b.getStart());
        }
        Address e = toAddr(0x02000800L);
        currentProgram.getSymbolTable().addExternalEntryPoint(e);
        createFunction(e, "_start");
    }
}
