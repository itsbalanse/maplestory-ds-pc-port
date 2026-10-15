// Export functions with their instructions and raw P-code for the static recompiler.
// Output (env PCODE_OUT), line format:
//   F <entry> <thumb 0/1> <name>
//   B <start> <end>                       body range (inclusive start, exclusive end)
//   I <addr> <len> <thumb> <bytes-hex> ; <disasm>
//   P <opcode> <out|-> <in0> <in1> ...    varnode = space:offset:size  (space: r=register u=unique c=const m=ram)
//   J <from> <to>                         computed jump target recovered by analysis
// Script args: optional "fn=<hexaddr>" to limit to specific functions.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.address.*;
import ghidra.program.model.pcode.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.lang.*;
import java.io.*;
import java.util.*;

public class ExportPcode extends GhidraScript {
    PrintWriter pw;
    Register tmode;

    String vn(Varnode v) {
        if (v == null) return "-";
        String sp;
        if (v.isRegister()) sp = "r";
        else if (v.isUnique()) sp = "u";
        else if (v.isConstant()) sp = "c";
        else if (v.isAddress()) sp = v.getAddress().getAddressSpace().isOverlaySpace() ? "o" : "m";
        else sp = v.getAddress().getAddressSpace().getName();
        return sp + ":" + Long.toHexString(v.getOffset()) + ":" + v.getSize();
    }

    public void run() throws Exception {
        String out = System.getenv("PCODE_OUT");
        pw = new PrintWriter(new BufferedWriter(new FileWriter(out)));
        tmode = currentProgram.getRegister("TMode");
        Set<Long> only = new HashSet<>();
        for (String a : getScriptArgs()) if (a.startsWith("fn=")) only.add(Long.parseLong(a.substring(3), 16));
        // register name table
        for (Register r : currentProgram.getLanguage().getRegisters()) {
            pw.println("R " + Long.toHexString(r.getAddress().getOffset()) + " " + r.getMinimumByteSize() + " " + r.getName());
        }
        Language lang = currentProgram.getLanguage();
        for (int i = 0; i < lang.getNumberOfUserDefinedOpNames(); i++) pw.println("U " + i + " " + lang.getUserDefinedOpName(i));
        Listing listing = currentProgram.getListing();
        FunctionIterator it = currentProgram.getFunctionManager().getFunctions(true);
        while (it.hasNext()) {
            Function f = it.next();
            if (monitor.isCancelled()) break;
            long entry = f.getEntryPoint().getOffset();
            if (!only.isEmpty() && !only.contains(entry)) continue;
            boolean thumb = isThumb(f.getEntryPoint());
            pw.println("F " + Long.toHexString(entry) + " " + (thumb ? 1 : 0) + " " + f.getEntryPoint().getAddressSpace().getName() + " " + f.getName());
            for (AddressRange r : f.getBody()) {
                pw.println("B " + Long.toHexString(r.getMinAddress().getOffset()) + " " + Long.toHexString(r.getMaxAddress().getOffset() + 1));
            }
            InstructionIterator ii = listing.getInstructions(f.getBody(), true);
            while (ii.hasNext()) {
                Instruction ins = ii.next();
                byte[] b = ins.getBytes();
                StringBuilder hx = new StringBuilder();
                for (byte x : b) hx.append(String.format("%02x", x & 0xff));
                pw.println("I " + Long.toHexString(ins.getAddress().getOffset()) + " " + ins.getLength() + " " +
                           (isThumb(ins.getAddress()) ? 1 : 0) + " " + hx + " ; " + ins.toString());
                for (PcodeOp op : ins.getPcode()) {
                    StringBuilder sb = new StringBuilder("P ").append(op.getMnemonic()).append(' ').append(vn(op.getOutput()));
                    for (int i = 0; i < op.getNumInputs(); i++) sb.append(' ').append(vn(op.getInput(i)));
                    pw.println(sb);
                }
                FlowType ft = ins.getFlowType();
                if (ft.isComputed()) {
                    for (Reference ref : ins.getReferencesFrom()) {
                        if (ref.getReferenceType().isFlow())
                            pw.println("J " + Long.toHexString(ins.getAddress().getOffset()) + " " + Long.toHexString(ref.getToAddress().getOffset()));
                    }
                }
            }
        }
        pw.close();
    }

    boolean isThumb(Address a) {
        if (tmode == null) return false;
        java.math.BigInteger v = currentProgram.getProgramContext().getValue(tmode, a, false);
        return v != null && v.intValue() == 1;
    }
}
