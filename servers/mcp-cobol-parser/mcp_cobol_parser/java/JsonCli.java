// mcp_cobol_parser/java/JsonCli.java
package com.astra.proleap;

import io.proleap.cobol.asg.metamodel.Program;
import io.proleap.cobol.asg.runner.impl.CobolParserRunnerImpl;
import io.proleap.cobol.preprocessor.CobolPreprocessor;

import java.io.File;
import java.nio.file.Files;
import java.util.*;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class JsonCli {

  /* -------------------- utils -------------------- */
  private static String esc(String s) {
    return s == null ? "" :
        s.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n").replace("\r", "\\r");
  }

  @SuppressWarnings("unchecked")
  private static <T> T call(Object target, String method) {
    if (target == null) return null;
    try {
      var m = target.getClass().getMethod(method);
      m.setAccessible(true);
      return (T) m.invoke(target);
    } catch (Throwable ignore) { return null; }
  }

  private static String toJsonArrayStrings(Collection<String> items) {
    var sb = new StringBuilder();
    sb.append("[");
    boolean first = true;
    for (String it : new LinkedHashSet<>(items)) {
      if (!first) sb.append(",");
      sb.append("\"").append(esc(it)).append("\"");
      first = false;
    }
    sb.append("]");
    return sb.toString();
  }

  /* -------------------- source scanners -------------------- */

  private static List<String> scanCopybooks(String source) {
    // Lightweight COPY detector (skip comment lines)
    List<String> out = new ArrayList<>();
    Pattern p = Pattern.compile("(?im)^(?!\\s{0,6}[*/])[^\\n]*\\bCOPY\\s+([A-Z0-9_-]+)");
    Matcher m = p.matcher(source);
    while (m.find()) {
      var name = m.group(1);
      if (name != null && !name.isEmpty()) out.add(name.toUpperCase(Locale.ROOT));
    }
    return out;
  }

  private static List<String> scanParagraphHeaders(String source, boolean fixed) {
    // Paragraph labels: a word (letters/digits/dash) on its own line ending in a dot.
    // Skip “... SECTION.” lines.
    List<String> out = new ArrayList<>();
    Pattern header = Pattern.compile("(?im)^\\s*([A-Za-z0-9][A-Za-z0-9-]*)\\s*\\.$");
    Pattern section = Pattern.compile("(?i)\\bSECTION\\s*\\.$");
    for (String raw : source.split("\\R")) {
      String line = raw;
      // Common fixed-format comment guards: col 7 * or / ; general * or *> anywhere by trimming
      if (line.length() >= 7 && (line.charAt(6) == '*' || line.charAt(6) == '/')) continue;
      var t = line.trim();
      if (t.startsWith("*") || t.startsWith("*>")) continue;
      if (section.matcher(line).find()) continue;
      var m = header.matcher(line);
      if (m.find()) {
        var name = m.group(1);
        if (name != null && !name.isEmpty()) out.add(name.toUpperCase(Locale.ROOT));
      }
    }
    return out;
  }

  private static Map<String, int[]> paragraphSpans(String source, List<String> paraNames) {
    // Return start/end char indices for each paragraph body
    Map<String, int[]> spans = new LinkedHashMap<>();
    // Build regex to find headers again, but capture positions
    Pattern header = Pattern.compile("(?im)^\\s*([A-Za-z0-9][A-Za-z0-9-]*)\\s*\\.$");
    Matcher m = header.matcher(source);
    List<int[]> hdrs = new ArrayList<>();
    List<String> names = new ArrayList<>();
    while (m.find()) {
      String n = m.group(1).toUpperCase(Locale.ROOT);
      if (paraNames.contains(n)) {
        hdrs.add(new int[]{m.start(), m.end()});
        names.add(n);
      }
    }
    for (int i = 0; i < names.size(); i++) {
      int bodyStart = hdrs.get(i)[1]; // after the header line
      int bodyEnd = (i + 1 < names.size()) ? hdrs.get(i + 1)[0] : source.length();
      spans.put(names.get(i), new int[]{bodyStart, bodyEnd});
    }
    return spans;
  }

  private static List<String> scanPerforms(String body) {
    // PERFORM PARA [THRU PARA2] ; grab first target (and THRU target as an extra edge)
    List<String> out = new ArrayList<>();
    Pattern p = Pattern.compile("(?im)\\bPERFORM\\s+([A-Z0-9-]+)(?:\\s+THRU\\s+([A-Z0-9-]+))?");
    Matcher m = p.matcher(body);
    while (m.find()) {
      out.add(m.group(1).toUpperCase(Locale.ROOT));
      if (m.group(2) != null) out.add(m.group(2).toUpperCase(Locale.ROOT));
    }
    return out;
  }

  private static List<Map<String,Object>> scanCalls(String body) {
    // CALL 'PROG' | "PROG" | identifier
    List<Map<String,Object>> out = new ArrayList<>();
    Pattern p = Pattern.compile("(?im)\\bCALL\\s+(?:'([^']+)'|\"([^\"]+)\"|([A-Z0-9-]+))");
    Matcher m = p.matcher(body);
    while (m.find()) {
      String quoted = m.group(1) != null ? m.group(1) : m.group(2);
      String ident = m.group(3);
      if (quoted != null) {
        out.add(Map.of("target", quoted.toUpperCase(Locale.ROOT), "dynamic", false));
      } else if (ident != null) {
        out.add(Map.of("target", ident.toUpperCase(Locale.ROOT), "dynamic", true));
      }
    }
    return out;
  }

  private static List<Map<String,Object>> scanIo(String body) {
    // OPEN/READ/WRITE/REWRITE/CLOSE [INPUT|OUTPUT|I-O|EXTEND] file-name
    List<Map<String,Object>> out = new ArrayList<>();
    Pattern p = Pattern.compile("(?im)\\b(OPEN|READ|WRITE|REWRITE|CLOSE)\\s+(?:INPUT|OUTPUT|I-?O|EXTEND\\s+)?([A-Z0-9-]+)");
    Matcher m = p.matcher(body);
    while (m.find()) {
      String op = m.group(1).toUpperCase(Locale.ROOT);
      String ds = m.group(2).toUpperCase(Locale.ROOT);
      out.add(new LinkedHashMap<>(Map.of("op", op, "dataset_ref", ds, "fields", List.of())));
    }
    return out;
  }

  /* -------------------- main -------------------- */

  public static void main(String[] args) {
    if (args.length < 1) {
      System.err.println("{\"status\":\"error\",\"message\":\"missing input file\"}");
      System.exit(2);
    }
    String in = args[0];

    String fmtEnv = System.getenv("COBOL_SOURCE_FORMAT");
    CobolPreprocessor.CobolSourceFormatEnum fmt =
        "VARIABLE".equalsIgnoreCase(fmtEnv)
            ? CobolPreprocessor.CobolSourceFormatEnum.VARIABLE
            : CobolPreprocessor.CobolSourceFormatEnum.FIXED;

    try {
      File f = new File(in);
      if (!f.isFile()) {
        System.out.println("{\"status\":\"error\",\"message\":\"file not found: " + esc(f.getAbsolutePath()) + "\"}");
        System.exit(3);
      }

      // Parse with ProLeap (ensures source is syntactically valid COBOL)
      CobolParserRunnerImpl runner = new CobolParserRunnerImpl();
      Program program = runner.analyzeFile(f, fmt);

      String src = new String(Files.readAllBytes(f.toPath()));
      boolean isFixed = (fmt == CobolPreprocessor.CobolSourceFormatEnum.FIXED);

      // Try ASG programId
      String programId = null;
      Collection<?> cus = call(program, "getCompilationUnits");
      Object cu = (cus != null && !cus.isEmpty()) ? cus.iterator().next() : null;
      if (cu != null) programId = call(cu, "getName");

      // Division presence flags
      Object pu = call(cu, "getProgramUnit");
      boolean hasId = call(pu, "getIdentificationDivision") != null;
      boolean hasEnv = call(pu, "getEnvironmentDivision") != null;
      boolean hasData = call(pu, "getDataDivision") != null;
      boolean hasProc = call(pu, "getProcedureDivision") != null;

      // Paragraph names (ASG if possible; else heuristic)
      List<String> paraNames = new ArrayList<>();
      Collection<?> paras = call(call(pu, "getProcedureDivision"), "getParagraphs");
      if (paras != null) {
        for (Object p : paras) {
          String n = call(p, "getName");
          if (n != null && !n.isEmpty()) paraNames.add(n.toUpperCase(Locale.ROOT));
        }
      }
      if (paraNames.isEmpty()) {
        paraNames = scanParagraphHeaders(src, isFixed);
      }

      // Paragraph spans and per-paragraph scans
      Map<String,int[]> spans = paragraphSpans(src, paraNames);
      List<String> copybooks = scanCopybooks(src);

      // Build JSON
      StringBuilder json = new StringBuilder(16384);
      json.append("{");
      json.append("\"status\":\"ok\",");
      json.append("\"engine\":\"JsonCli\",");
      json.append("\"programId\":\"").append(esc(programId)).append("\",");
      json.append("\"sourceFormat\":\"").append(fmt.name()).append("\",");
      json.append("\"file\":\"").append(esc(f.getAbsolutePath())).append("\",");

      json.append("\"divisions\":{");
      json.append("\"identification\":").append(hasId ? "{\"present\":true}" : "{}").append(",");
      json.append("\"environment\":").append(hasEnv ? "{\"present\":true}" : "{}").append(",");
      json.append("\"data\":").append(hasData ? "{\"present\":true}" : "{}").append(",");
      json.append("\"procedure\":").append(hasProc ? "{\"present\":true}" : "{}");
      json.append("},");

      // Paragraphs with performs/calls/io_ops
      json.append("\"paragraphs\":[");
      boolean firstP = true;
      for (var entry : spans.entrySet()) {
        String name = entry.getKey();
        int[] span = entry.getValue();
        String body = src.substring(span[0], span[1]);

        List<String> performs = scanPerforms(body);
        List<Map<String,Object>> calls = scanCalls(body);
        List<Map<String,Object>> ioops = scanIo(body);

        if (!firstP) json.append(",");
        json.append("{\"name\":\"").append(esc(name)).append("\",");
        // performs
        json.append("\"performs\":[");
        for (int i = 0; i < performs.size(); i++) {
          if (i > 0) json.append(",");
          json.append("\"").append(esc(performs.get(i))).append("\"");
        }
        json.append("],");
        // calls
        json.append("\"calls\":[");
        for (int i = 0; i < calls.size(); i++) {
          if (i > 0) json.append(",");
          Map<String,Object> c = calls.get(i);
          json.append("{\"target\":\"").append(esc(String.valueOf(c.get("target")))).append("\",");
          json.append("\"dynamic\":").append(Boolean.TRUE.equals(c.get("dynamic")) ? "true" : "false").append("}");
        }
        json.append("],");
        // io_ops
        json.append("\"io_ops\":[");
        for (int i = 0; i < ioops.size(); i++) {
          if (i > 0) json.append(",");
          @SuppressWarnings("unchecked")
          Map<String,Object> io = ioops.get(i);
          json.append("{\"op\":\"").append(esc(String.valueOf(io.get("op")))).append("\",");
          json.append("\"dataset_ref\":\"").append(esc(String.valueOf(io.get("dataset_ref")))).append("\",");
          json.append("\"fields\":[]}");
        }
        json.append("]}");
        firstP = false;
      }
      json.append("],");

      // copybooks_used
      json.append("\"copybooks_used\":").append(toJsonArrayStrings(copybooks)).append(",");

      // notes
      json.append("\"notes\":[");
      json.append("\"sourceFormat=").append(fmt.name()).append("\",");
      json.append("\"raw_source_embedded=true;len=").append(src.length()).append("\"");
      json.append("]");

      json.append("}");
      System.out.println(json.toString());

    } catch (Throwable t) {
      String msg = t.getMessage();
      if (msg == null) msg = t.getClass().getName();
      System.out.println("{\"status\":\"error\",\"message\":\"" + esc(msg) + "\"}");
      System.exit(1);
    }
  }
}