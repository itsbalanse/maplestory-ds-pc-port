// Add a code image as a Ghidra overlay block. Args: <block name> <file> <hex load address>
import ghidra.app.script.GhidraScript;
import java.io.*;
import java.nio.file.*;
public class AddImage extends GhidraScript {
    public void run() throws Exception {
        String[] a = getScriptArgs();
        byte[] data = Files.readAllBytes(Paths.get(a[1]));
        if (currentProgram.getMemory().getBlock(a[0]) != null) { println("block exists: " + a[0]); return; }
        currentProgram.getMemory().createInitializedBlock(a[0], toAddr(Long.parseLong(a[2], 16)),
            new ByteArrayInputStream(data), data.length, monitor, true);
        println("added " + a[0] + " (" + data.length + " bytes)");
    }
}
