import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import java.io.*;
public class DumpAll extends GhidraScript {
    public void run() throws Exception {
        PrintWriter pw = new PrintWriter(new FileWriter(System.getenv("DECOMP_OUT")));
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        FunctionIterator it = currentProgram.getFunctionManager().getFunctions(true);
        while (it.hasNext()) {
            Function f = it.next();
            DecompileResults r = di.decompileFunction(f, 30, monitor);
            pw.println("// ===== " + f.getName() + " @ " + f.getEntryPoint());
            if (r.decompileCompleted()) pw.println(r.getDecompiledFunction().getC());
        }
        pw.close();
    }
}
