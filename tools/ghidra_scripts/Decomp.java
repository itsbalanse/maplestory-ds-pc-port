// Decompile functions: args are either 0xADDR or "str:TEXT" (functions referencing a string containing TEXT).
// Output appended to file given by env DECOMP_OUT or ./decomp_out.c
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.address.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.mem.*;
import java.io.*;
import java.util.*;

public class Decomp extends GhidraScript {
    public void run() throws Exception {
        String outPath = System.getenv("DECOMP_OUT");
        if (outPath == null) outPath = "decomp_out.c";
        PrintWriter pw = new PrintWriter(new FileWriter(outPath, false));
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        Set<Function> funcs = new LinkedHashSet<>();
        Listing listing = currentProgram.getListing();
        for (String a : getScriptArgs()) {
            if (a.startsWith("str:")) {
                String needle = a.substring(4);
                Memory mem = currentProgram.getMemory();
                byte[] nb = needle.getBytes("ISO-8859-1");
                Address start = mem.getMinAddress();
                while (true) {
                    Address found = mem.findBytes(start, nb, null, true, monitor);
                    if (found == null) break;
                    pw.println("// string '" + needle + "' at " + found);
                    // find refs to the start of the containing C string
                    Address s = found;
                    while (true) { try { byte b = mem.getByte(s.subtract(1)); if (b == 0) break; s = s.subtract(1);} catch (Exception e) {break;} }
                    for (Reference r : getReferencesTo(s)) {
                        Function f = getFunctionContaining(r.getFromAddress());
                        pw.println("//   ref from " + r.getFromAddress() + " in " + (f==null?"?":f.getName()));
                        if (f != null) funcs.add(f);
                    }
                    // also raw pointer search (literal pools)
                    byte[] pb = new byte[4]; long v = s.getOffset();
                    pb[0]=(byte)v; pb[1]=(byte)(v>>8); pb[2]=(byte)(v>>16); pb[3]=(byte)(v>>24);
                    Address ps = mem.getMinAddress();
                    while (true) {
                        Address pf = mem.findBytes(ps, pb, null, true, monitor);
                        if (pf == null) break;
                        for (Reference r : getReferencesTo(pf)) {
                            Function f = getFunctionContaining(r.getFromAddress());
                            pw.println("//   pool " + pf + " ref from " + r.getFromAddress() + " in " + (f==null?"?":f.getName()));
                            if (f != null) funcs.add(f);
                        }
                        ps = pf.add(1);
                    }
                    start = found.add(1);
                }
            } else if (a.startsWith("callers:")) {
                Address ad = toAddr(a.substring(8));
                for (Reference r : getReferencesTo(ad)) {
                    Function f = getFunctionContaining(r.getFromAddress());
                    pw.println("// caller " + r.getFromAddress() + " in " + (f==null?"?":f.getName()));
                    if (f != null) funcs.add(f);
                }
            } else {
                Address ad = toAddr(a);
                Function f = getFunctionContaining(ad);
                if (f == null) { disassemble(ad); f = createFunction(ad, null); }
                if (f != null) funcs.add(f); else pw.println("// no function at " + a);
            }
        }
        for (Function f : funcs) {
            DecompileResults res = di.decompileFunction(f, 60, monitor);
            pw.println("// ===== " + f.getName() + " @ " + f.getEntryPoint());
            if (res.decompileCompleted()) pw.println(res.getDecompiledFunction().getC());
            else pw.println("// decompile failed: " + res.getErrorMessage());
        }
        pw.close();
    }
}
