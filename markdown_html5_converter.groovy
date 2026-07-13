#!/usr/bin/env groovy

/**
 * Markdown -> HTML5 converter for Groovy 2.5.6
 *
 * Design:
 * 1) Lexing (line + inline tokenization)
 * 2) AST building
 * 3) HTML5 rendering
 *
 * Constraints:
 * - No regular expressions
 * - Supports common Markdown formats:
 *   headings, paragraphs, unordered/ordered lists, blockquotes,
 *   fenced code, horizontal rules, tables, links/images,
 *   inline code, strong/emphasis, strike.
 * - Supports source text containing escaped '\n'
 */
class MarkdownHtml5Converter {
    static final String NEWLINE = "\n"

    String convert(String markdownSource) {
        String normalized = decodeEscapedNewlines(markdownSource)
        List<String> lines = splitLines(normalized)
        Map ast = parseDocument(lines)
        return renderHtml5(ast)
    }

    // ---------- Phase 0: source normalization ----------
    String decodeEscapedNewlines(String source) {
        if (source == null || source.isEmpty()) {
            return ""
        }
        StringBuilder out = new StringBuilder()
        int i = 0
        while (i < source.length()) {
            char c = source.charAt(i)
            if (c == '\\' && i + 1 < source.length()) {
                char n = source.charAt(i + 1)
                if (n == 'n') {
                    out.append('\n')
                    i += 2
                    continue
                }
                if (n == 't') {
                    out.append('\t')
                    i += 2
                    continue
                }
                if (n == '\\') {
                    out.append('\\')
                    i += 2
                    continue
                }
            }
            out.append(c)
            i++
        }
        return out.toString()
    }

    List<String> splitLines(String text) {
        List<String> lines = []
        StringBuilder current = new StringBuilder()
        int i = 0
        while (i < text.length()) {
            char c = text.charAt(i)
            if (c == '\r') {
                if (i + 1 < text.length() && text.charAt(i + 1) == '\n') {
                    i++
                }
                lines << current.toString()
                current.setLength(0)
            } else if (c == '\n') {
                lines << current.toString()
                current.setLength(0)
            } else {
                current.append(c)
            }
            i++
        }
        lines << current.toString()
        return lines
    }

    // ---------- Phase 1: block parsing ----------
    Map parseDocument(List<String> lines) {
        List<Map> blocks = []
        int i = 0
        while (i < lines.size()) {
            String line = lines[i]
            String trimmed = line.trim()

            if (trimmed.isEmpty()) {
                i++
                continue
            }

            Map heading = parseHeading(line)
            if (heading != null) {
                blocks << heading
                i++
                continue
            }

            if (isFenceStart(trimmed)) {
                Map result = parseFencedCode(lines, i)
                blocks << result.block
                i = result.nextIndex as int
                continue
            }

            if (isHorizontalRule(trimmed)) {
                blocks << [type: "hr"]
                i++
                continue
            }

            if (isUnorderedListItem(line)) {
                Map result = parseList(lines, i, false)
                blocks << result.block
                i = result.nextIndex as int
                continue
            }

            if (isOrderedListItem(line)) {
                Map result = parseList(lines, i, true)
                blocks << result.block
                i = result.nextIndex as int
                continue
            }

            if (isBlockquote(line)) {
                Map result = parseBlockquote(lines, i)
                blocks << result.block
                i = result.nextIndex as int
                continue
            }

            if (isTableRow(line) && i + 1 < lines.size() && isTableSeparator(lines[i + 1])) {
                Map result = parseTable(lines, i)
                blocks << result.block
                i = result.nextIndex as int
                continue
            }

            Map result = parseParagraph(lines, i)
            blocks << result.block
            i = result.nextIndex as int
        }
        return [type: "document", children: blocks]
    }

    Map parseHeading(String line) {
        String trimmed = line.trim()
        if (!trimmed.startsWith("#")) {
            return null
        }
        int level = 0
        while (level < trimmed.length() && trimmed.charAt(level) == '#') {
            level++
        }
        if (level < 1 || level > 6) {
            return null
        }
        if (level >= trimmed.length() || trimmed.charAt(level) != ' ') {
            return null
        }
        String content = trimmed.substring(level + 1).trim()
        return [type: "heading", level: level, children: parseInline(content)]
    }

    boolean isFenceStart(String trimmed) {
        return trimmed.startsWith("```")
    }

    Map parseFencedCode(List<String> lines, int start) {
        String first = lines[start].trim()
        String lang = first.length() > 3 ? first.substring(3).trim() : ""
        StringBuilder code = new StringBuilder()
        int i = start + 1
        while (i < lines.size()) {
            String line = lines[i]
            if (line.trim() == "```") {
                i++
                break
            }
            code.append(line)
            if (i + 1 < lines.size()) {
                code.append(NEWLINE)
            }
            i++
        }
        return [
            block: [
                type    : "code_block",
                language: lang,
                text    : code.toString()
            ],
            nextIndex: i
        ]
    }

    boolean isHorizontalRule(String trimmed) {
        if (trimmed.length() < 3) {
            return false
        }
        char marker = 0
        int count = 0
        for (int i = 0; i < trimmed.length(); i++) {
            char c = trimmed.charAt(i)
            if (c == ' ') {
                continue
            }
            if (marker == 0) {
                if (c != '-' && c != '*' && c != '_') {
                    return false
                }
                marker = c
            } else if (c != marker) {
                return false
            }
            count++
        }
        return count >= 3
    }

    boolean isUnorderedListItem(String line) {
        String trimmed = line.trim()
        if (trimmed.length() < 2) {
            return false
        }
        char c = trimmed.charAt(0)
        return (c == '-' || c == '*' || c == '+') && trimmed.charAt(1) == ' '
    }

    boolean isOrderedListItem(String line) {
        String trimmed = line.trim()
        if (trimmed.length() < 3) {
            return false
        }
        int i = 0
        while (i < trimmed.length() && isDigit(trimmed.charAt(i))) {
            i++
        }
        if (i == 0 || i + 1 >= trimmed.length()) {
            return false
        }
        return trimmed.charAt(i) == '.' && trimmed.charAt(i + 1) == ' '
    }

    Map parseList(List<String> lines, int start, boolean ordered) {
        List<Map> items = []
        int i = start
        while (i < lines.size()) {
            String line = lines[i]
            if (line.trim().isEmpty()) {
                break
            }
            if (ordered && !isOrderedListItem(line)) {
                break
            }
            if (!ordered && !isUnorderedListItem(line)) {
                break
            }
            String content = extractListItemContent(line, ordered)
            items << [type: "list_item", children: parseInline(content)]
            i++
        }
        return [
            block: [type: ordered ? "ordered_list" : "unordered_list", items: items],
            nextIndex: i
        ]
    }

    String extractListItemContent(String line, boolean ordered) {
        String trimmed = line.trim()
        if (!ordered) {
            return trimmed.substring(2).trim()
        }
        int i = 0
        while (i < trimmed.length() && isDigit(trimmed.charAt(i))) {
            i++
        }
        return trimmed.substring(i + 2).trim()
    }

    boolean isBlockquote(String line) {
        String trimmed = line.trim()
        return trimmed.startsWith(">") && (trimmed.length() == 1 || trimmed.charAt(1) == ' ')
    }

    Map parseBlockquote(List<String> lines, int start) {
        List<String> quoteLines = []
        int i = start
        while (i < lines.size()) {
            String line = lines[i]
            if (!isBlockquote(line)) {
                break
            }
            String trimmed = line.trim()
            String content = trimmed.length() > 1 ? trimmed.substring(1).trim() : ""
            quoteLines << content
            i++
        }
        Map inner = parseDocument(quoteLines)
        return [block: [type: "blockquote", children: inner.children], nextIndex: i]
    }

    boolean isTableRow(String line) {
        String trimmed = line.trim()
        return trimmed.contains("|")
    }

    boolean isTableSeparator(String line) {
        String trimmed = line.trim()
        if (!trimmed.contains("|")) {
            return false
        }
        List<String> cells = splitTableCells(trimmed)
        if (cells.isEmpty()) {
            return false
        }
        for (String cell : cells) {
            String c = cell.trim()
            if (c.isEmpty()) {
                continue
            }
            for (int i = 0; i < c.length(); i++) {
                char ch = c.charAt(i)
                if (ch != '-' && ch != ':') {
                    return false
                }
            }
        }
        return true
    }

    Map parseTable(List<String> lines, int start) {
        List<String> headerCells = splitTableCells(lines[start].trim())
        int i = start + 2 // skip separator line
        List<List<String>> body = []
        while (i < lines.size()) {
            String line = lines[i]
            if (!isTableRow(line) || line.trim().isEmpty()) {
                break
            }
            body << splitTableCells(line.trim())
            i++
        }
        return [
            block: [
                type  : "table",
                header: headerCells.collect { parseInline(it.trim()) },
                rows  : body.collect { row -> row.collect { parseInline(it.trim()) } }
            ],
            nextIndex: i
        ]
    }

    List<String> splitTableCells(String line) {
        String work = line
        if (work.startsWith("|")) {
            work = work.substring(1)
        }
        if (work.endsWith("|")) {
            work = work.substring(0, work.length() - 1)
        }
        List<String> cells = []
        StringBuilder buf = new StringBuilder()
        for (int i = 0; i < work.length(); i++) {
            char c = work.charAt(i)
            if (c == '|') {
                cells << buf.toString()
                buf.setLength(0)
            } else {
                buf.append(c)
            }
        }
        cells << buf.toString()
        return cells
    }

    Map parseParagraph(List<String> lines, int start) {
        StringBuilder text = new StringBuilder()
        int i = start
        while (i < lines.size()) {
            String line = lines[i]
            String trimmed = line.trim()
            if (trimmed.isEmpty()) {
                break
            }
            if (parseHeading(line) != null || isFenceStart(trimmed) || isHorizontalRule(trimmed)
                || isUnorderedListItem(line) || isOrderedListItem(line)
                || isBlockquote(line)
                || (isTableRow(line) && i + 1 < lines.size() && isTableSeparator(lines[i + 1]))) {
                break
            }
            if (text.length() > 0) {
                text.append(' ')
            }
            text.append(trimmed)
            i++
        }
        return [block: [type: "paragraph", children: parseInline(text.toString())], nextIndex: i]
    }

    // ---------- Phase 2: inline tokenization ----------
    List<Map> parseInline(String text) {
        List<Map> nodes = []
        StringBuilder plain = new StringBuilder()
        int i = 0
        while (i < text.length()) {
            if (startsWithAt(text, i, "![") ) {
                Map image = parseImage(text, i)
                if (image != null) {
                    flushPlain(nodes, plain)
                    nodes << image.node
                    i = image.nextIndex as int
                    continue
                }
            }
            if (startsWithAt(text, i, "[")) {
                Map link = parseLink(text, i)
                if (link != null) {
                    flushPlain(nodes, plain)
                    nodes << link.node
                    i = link.nextIndex as int
                    continue
                }
            }
            if (startsWithAt(text, i, "~~")) {
                Map strike = parseDelimited(text, i, "~~", "strike")
                if (strike != null) {
                    flushPlain(nodes, plain)
                    nodes << strike.node
                    i = strike.nextIndex as int
                    continue
                }
            }
            if (startsWithAt(text, i, "**")) {
                Map strong = parseDelimited(text, i, "**", "strong")
                if (strong != null) {
                    flushPlain(nodes, plain)
                    nodes << strong.node
                    i = strong.nextIndex as int
                    continue
                }
            }
            if (startsWithAt(text, i, "*")) {
                Map em = parseDelimited(text, i, "*", "em")
                if (em != null) {
                    flushPlain(nodes, plain)
                    nodes << em.node
                    i = em.nextIndex as int
                    continue
                }
            }
            if (startsWithAt(text, i, "_")) {
                Map em = parseDelimited(text, i, "_", "em")
                if (em != null) {
                    flushPlain(nodes, plain)
                    nodes << em.node
                    i = em.nextIndex as int
                    continue
                }
            }
            if (startsWithAt(text, i, "`")) {
                int close = findClosing(text, i + 1, "`")
                if (close >= 0) {
                    flushPlain(nodes, plain)
                    String code = text.substring(i + 1, close)
                    nodes << [type: "code", text: code]
                    i = close + 1
                    continue
                }
            }
            plain.append(text.charAt(i))
            i++
        }
        flushPlain(nodes, plain)
        return nodes
    }

    Map parseDelimited(String text, int start, String marker, String type) {
        int close = findClosing(text, start + marker.length(), marker)
        if (close < 0) {
            return null
        }
        String inner = text.substring(start + marker.length(), close)
        return [
            node     : [type: type, children: parseInline(inner)],
            nextIndex: close + marker.length()
        ]
    }

    Map parseLink(String text, int start) {
        int closeLabel = findChar(text, start + 1, ']')
        if (closeLabel < 0 || closeLabel + 1 >= text.length() || text.charAt(closeLabel + 1) != '(') {
            return null
        }
        int closeUrl = findChar(text, closeLabel + 2, ')')
        if (closeUrl < 0) {
            return null
        }
        String label = text.substring(start + 1, closeLabel)
        String url = text.substring(closeLabel + 2, closeUrl).trim()
        return [
            node     : [type: "link", href: url, children: parseInline(label)],
            nextIndex: closeUrl + 1
        ]
    }

    Map parseImage(String text, int start) {
        if (!startsWithAt(text, start, "![")) {
            return null
        }
        int closeAlt = findChar(text, start + 2, ']')
        if (closeAlt < 0 || closeAlt + 1 >= text.length() || text.charAt(closeAlt + 1) != '(') {
            return null
        }
        int closeUrl = findChar(text, closeAlt + 2, ')')
        if (closeUrl < 0) {
            return null
        }
        String alt = text.substring(start + 2, closeAlt)
        String src = text.substring(closeAlt + 2, closeUrl).trim()
        return [
            node     : [type: "image", alt: alt, src: src],
            nextIndex: closeUrl + 1
        ]
    }

    int findClosing(String text, int from, String marker) {
        int i = from
        while (i <= text.length() - marker.length()) {
            if (startsWithAt(text, i, marker)) {
                return i
            }
            i++
        }
        return -1
    }

    int findChar(String text, int from, char target) {
        int i = from
        while (i < text.length()) {
            if (text.charAt(i) == target) {
                return i
            }
            i++
        }
        return -1
    }

    boolean startsWithAt(String text, int index, String marker) {
        if (index < 0 || index + marker.length() > text.length()) {
            return false
        }
        for (int i = 0; i < marker.length(); i++) {
            if (text.charAt(index + i) != marker.charAt(i)) {
                return false
            }
        }
        return true
    }

    void flushPlain(List<Map> nodes, StringBuilder plain) {
        if (plain.length() == 0) {
            return
        }
        nodes << [type: "text", text: plain.toString()]
        plain.setLength(0)
    }

    boolean isDigit(char c) {
        return c >= '0' && c <= '9'
    }

    // ---------- Phase 3: HTML5 rendering ----------
    String renderHtml5(Map documentAst) {
        StringBuilder out = new StringBuilder()
        out.append("<!doctype html>\n")
        out.append("<html lang=\"zh-CN\">\n")
        out.append("<head>\n")
        out.append("  <meta charset=\"UTF-8\" />\n")
        out.append("  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />\n")
        out.append("  <title>Markdown Render</title>\n")
        out.append("  <style>\n")
        out.append("    body { font-family: Arial, sans-serif; line-height: 1.6; margin: 24px; }\n")
        out.append("    pre { background: #f5f5f5; padding: 12px; overflow-x: auto; }\n")
        out.append("    code { background: #f1f1f1; padding: 1px 4px; }\n")
        out.append("    table { border-collapse: collapse; width: 100%; margin: 12px 0; }\n")
        out.append("    th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }\n")
        out.append("    blockquote { margin: 10px 0; padding-left: 12px; border-left: 4px solid #ddd; color: #555; }\n")
        out.append("  </style>\n")
        out.append("</head>\n")
        out.append("<body>\n")
        for (Map block : (List<Map>) documentAst.children) {
            out.append(renderBlock(block))
        }
        out.append("</body>\n")
        out.append("</html>\n")
        return out.toString()
    }

    String renderBlock(Map block) {
        String type = block.type as String
        if (type == "heading") {
            int level = block.level as int
            return "<h${level}>${renderInline(block.children as List<Map>)}</h${level}>\n"
        }
        if (type == "paragraph") {
            return "<p>${renderInline(block.children as List<Map>)}</p>\n"
        }
        if (type == "unordered_list") {
            StringBuilder out = new StringBuilder("<ul>\n")
            for (Map item : (List<Map>) block.items) {
                out.append("<li>${renderInline(item.children as List<Map>)}</li>\n")
            }
            out.append("</ul>\n")
            return out.toString()
        }
        if (type == "ordered_list") {
            StringBuilder out = new StringBuilder("<ol>\n")
            for (Map item : (List<Map>) block.items) {
                out.append("<li>${renderInline(item.children as List<Map>)}</li>\n")
            }
            out.append("</ol>\n")
            return out.toString()
        }
        if (type == "blockquote") {
            StringBuilder out = new StringBuilder("<blockquote>\n")
            for (Map child : (List<Map>) block.children) {
                out.append(renderBlock(child))
            }
            out.append("</blockquote>\n")
            return out.toString()
        }
        if (type == "code_block") {
            String lang = escapeHtml(block.language as String ?: "")
            String klass = lang.isEmpty() ? "" : " class=\"language-${lang}\""
            return "<pre><code${klass}>${escapeHtml(block.text as String ?: "")}</code></pre>\n"
        }
        if (type == "hr") {
            return "<hr />\n"
        }
        if (type == "table") {
            StringBuilder out = new StringBuilder("<table>\n<thead><tr>")
            for (List<Map> cell : (List<List<Map>>) block.header) {
                out.append("<th>${renderInline(cell)}</th>")
            }
            out.append("</tr></thead>\n<tbody>\n")
            for (List<List<Map>> row : (List<List<List<Map>>>) block.rows) {
                out.append("<tr>")
                for (List<Map> cell : row) {
                    out.append("<td>${renderInline(cell)}</td>")
                }
                out.append("</tr>\n")
            }
            out.append("</tbody>\n</table>\n")
            return out.toString()
        }
        return ""
    }

    String renderInline(List<Map> nodes) {
        StringBuilder out = new StringBuilder()
        for (Map node : nodes) {
            String type = node.type as String
            if (type == "text") {
                out.append(escapeHtml(node.text as String ?: ""))
            } else if (type == "code") {
                out.append("<code>${escapeHtml(node.text as String ?: "")}</code>")
            } else if (type == "strong") {
                out.append("<strong>${renderInline(node.children as List<Map>)}</strong>")
            } else if (type == "em") {
                out.append("<em>${renderInline(node.children as List<Map>)}</em>")
            } else if (type == "strike") {
                out.append("<del>${renderInline(node.children as List<Map>)}</del>")
            } else if (type == "link") {
                out.append("<a href=\"${escapeAttr(node.href as String ?: "")}\">${renderInline(node.children as List<Map>)}</a>")
            } else if (type == "image") {
                out.append("<img src=\"${escapeAttr(node.src as String ?: "")}\" alt=\"${escapeAttr(node.alt as String ?: "")}\" />")
            }
        }
        return out.toString()
    }

    String escapeHtml(String text) {
        StringBuilder out = new StringBuilder()
        for (int i = 0; i < text.length(); i++) {
            char c = text.charAt(i)
            if (c == '&') out.append("&amp;")
            else if (c == '<') out.append("&lt;")
            else if (c == '>') out.append("&gt;")
            else if (c == '"') out.append("&quot;")
            else if (c == '\'') out.append("&#39;")
            else out.append(c)
        }
        return out.toString()
    }

    String escapeAttr(String text) {
        return escapeHtml(text)
    }
}

class Main {
    static void main(String[] args) {
        // If no input file is provided, use the sample from the requirement.
        String mdSource
        if (args.length > 0) {
            mdSource = new File(args[0]).getText("UTF-8")
        } else {
            mdSource = '''
### CPU 使用情况\\n- **CPU 总使用率**：约 7.1%（用户态 2.3%，系统态 2.3%，空闲 92.5%）。\\n- **CPU 使用率未超过 70%**，无需提示。\\n\\n### 内存使用情况\\n-\\n**内存总量**：1045835.1 MiB。\\n- **内存使用量**：470389.6 MiB（约 45%）。\\n- **内存使用率未超过 70%**，无需提示。\\n\\n### IO 使用情况\\n- **IO负载**：平均CPU等待IO 时间仅为 0.02%，IO 负载较低。\\n- **磁盘读写**：dm-15设备读写量最高，读取13079.08 kB/s，写入 14845.61 kB/s； sdb 设备读写量也较高，读取 13085.08 kB/s，写入 15695.74 kB/s。\\n\\n### 高资源占用进程\\n- **gaussdb 进程**（PID 1167002）占用 3.3G 内存，CPU 使用率 88.2%，是当前系统中占用资源最多的进程。\\n- **多个python 相关进程**（PID 1109779、1109814、1109782 等）占用 CPU 资源较高，但单个进程 CPU 使用率均未超过 100%。\\n\\n### 总结\\n- **总体 CPU、内存、IO 使用率均未超过 70%**，系统运行状态正常。\\n- **gaussdb进程**是当前系统中占用资源最多的进程，需关注其运行状态和性能表现。
'''
        }

        MarkdownHtml5Converter converter = new MarkdownHtml5Converter()
        String html = converter.convert(mdSource)
        println html
    }
}

Main.main(this.args as String[])
