#!/usr/bin/env groovy

import groovy.json.JsonOutput
import groovy.json.JsonSlurper

/**
 * Stateful Markdown parser for complex documents.
 *
 * Constraints:
 * - No regular expressions are used.
 * - Works with heading hierarchy, multiline key-value blocks,
 *   list values, fenced code blocks, and JSON payload blocks.
 */
class MarkdownNode {
    int level
    String title
    List<String> body = []
    Map<String, Object> fields = [:]
    List<MarkdownNode> children = []
}

class ComplexMarkdownParser {
    private final JsonSlurper jsonSlurper = new JsonSlurper()

    MarkdownNode parse(String content) {
        MarkdownNode root = new MarkdownNode(level: 0, title: 'ROOT')
        List<MarkdownNode> stack = [root]
        MarkdownNode current = root

        String currentField = null
        List<String> fieldBuffer = []
        boolean inFence = false

        List<String> lines = content.readLines()
        for (String rawLine : lines) {
            String line = rawLine.replace('\t', '    ')
            String trimmed = line.trim()

            if (startsFence(trimmed)) {
                if (currentField != null) {
                    fieldBuffer << trimmed
                } else {
                    current.body << line
                }
                inFence = !inFence
                continue
            }

            if (inFence) {
                if (currentField != null) {
                    fieldBuffer << line
                } else {
                    current.body << line
                }
                continue
            }

            Map heading = parseHeading(trimmed)
            if (heading != null) {
                flushField(current, currentField, fieldBuffer)
                currentField = null
                fieldBuffer = []

                MarkdownNode node = new MarkdownNode(
                    level: heading.level as int,
                    title: heading.title as String
                )
                while (!stack.isEmpty() && stack.last().level >= node.level) {
                    stack.remove(stack.size() - 1)
                }
                stack.last().children << node
                stack << node
                current = node
                continue
            }

            Map keyValue = parseKeyValue(trimmed)
            if (keyValue != null) {
                flushField(current, currentField, fieldBuffer)
                currentField = keyValue.key as String
                fieldBuffer = []
                String inlineValue = keyValue.value as String
                if (!inlineValue.isEmpty()) {
                    fieldBuffer << inlineValue
                }
                continue
            }

            if (currentField != null) {
                fieldBuffer << line
            } else {
                current.body << line
            }
        }

        flushField(current, currentField, fieldBuffer)
        return root
    }

    Map<String, Object> buildDiagnosisModel(MarkdownNode root) {
        List<Map<String, Object>> abilities = []
        for (MarkdownNode node : root.children) {
            if (!node.title.startsWith('Ability:')) {
                continue
            }
            String abilityId = node.title.substring('Ability:'.length()).trim()
            Map<String, Object> ability = new LinkedHashMap<>()
            ability['ability'] = abilityId
            ability['metadata'] = node.fields
            ability['steps'] = collectSteps(node)
            abilities << ability
        }
        return [abilities: abilities]
    }

    private List<Map<String, Object>> collectSteps(MarkdownNode abilityNode) {
        List<Map<String, Object>> steps = []
        for (MarkdownNode child : abilityNode.children) {
            if (!child.title.startsWith('Step')) {
                continue
            }
            Map<String, Object> step = new LinkedHashMap<>()
            step['id'] = child.title.trim()
            step['fields'] = child.fields
            step['body'] = normalizeBody(child.body)
            step['children'] = child.children.collect { MarkdownNode sub ->
                [
                    title : sub.title,
                    fields: sub.fields,
                    body  : normalizeBody(sub.body)
                ]
            }
            steps << step
        }
        return steps
    }

    private static String normalizeBody(List<String> bodyLines) {
        return bodyLines.join('\n').trim()
    }

    private static boolean startsFence(String line) {
        return line.startsWith('```')
    }

    private static Map parseHeading(String trimmed) {
        if (!trimmed.startsWith('#')) {
            return null
        }
        int level = 0
        while (level < trimmed.length() && trimmed.charAt(level) == '#') {
            level++
        }
        if (level == 0 || level >= trimmed.length()) {
            return null
        }
        if (trimmed.charAt(level) != ' ') {
            return null
        }
        String title = trimmed.substring(level + 1).trim()
        if (title.isEmpty()) {
            return null
        }
        return [level: level, title: title]
    }

    private static Map parseKeyValue(String trimmed) {
        if (trimmed.isEmpty()) {
            return null
        }
        if (trimmed.startsWith('- ') || trimmed.startsWith('#') || trimmed.startsWith('```')) {
            return null
        }
        int colon = trimmed.indexOf(':')
        if (colon <= 0) {
            return null
        }
        String key = trimmed.substring(0, colon).trim()
        if (key.isEmpty()) {
            return null
        }
        if (key.contains(' ')) {
            return null
        }
        String value = trimmed.substring(colon + 1).trim()
        return [key: key, value: value]
    }

    private void flushField(MarkdownNode node, String field, List<String> buffer) {
        if (field == null) {
            return
        }
        String raw = buffer.join('\n').trim()
        node.fields[field] = convertValue(raw)
    }

    private Object convertValue(String raw) {
        if (raw.isEmpty()) {
            return ''
        }

        List<String> lines = raw.readLines()
        if (isFenced(lines)) {
            List<String> inside = lines.subList(1, lines.size() - 1)
            String fencedContent = inside.join('\n').trim()
            Object jsonValue = tryParseJson(fencedContent)
            return jsonValue != null ? jsonValue : fencedContent
        }

        if (isBulletList(lines)) {
            return parseBulletList(lines)
        }

        Object jsonValue = tryParseJson(raw)
        return jsonValue != null ? jsonValue : raw
    }

    private static boolean isFenced(List<String> lines) {
        if (lines.size() < 2) {
            return false
        }
        String first = lines.first().trim()
        String last = lines.last().trim()
        return first.startsWith('```') && last == '```'
    }

    private static boolean isBulletList(List<String> lines) {
        boolean hasItem = false
        for (String line : lines) {
            String trimmed = line.trim()
            if (trimmed.isEmpty()) {
                continue
            }
            if (!trimmed.startsWith('- ')) {
                return false
            }
            hasItem = true
        }
        return hasItem
    }

    private static List<Object> parseBulletList(List<String> lines) {
        List<Object> values = []
        for (String line : lines) {
            String trimmed = line.trim()
            if (!trimmed.startsWith('- ')) {
                continue
            }
            String item = trimmed.substring(2).trim()
            values << item
        }
        return values
    }

    private Object tryParseJson(String text) {
        String trimmed = text.trim()
        if (trimmed.isEmpty()) {
            return null
        }
        if (!(trimmed.startsWith('{') || trimmed.startsWith('['))) {
            return null
        }
        try {
            return jsonSlurper.parseText(trimmed)
        } catch (Exception ignored) {
            return null
        }
    }
}

class ScriptMain {
    static void main(String[] args) {
        if (args.length < 1) {
            println 'Usage: groovy complex_md_parser.groovy <markdown-file>'
            System.exit(1)
        }

        File mdFile = new File(args[0])
        if (!mdFile.exists()) {
            println "File not found: ${mdFile.absolutePath}"
            System.exit(2)
        }

        String content = mdFile.getText('UTF-8')
        ComplexMarkdownParser parser = new ComplexMarkdownParser()
        MarkdownNode root = parser.parse(content)
        Map<String, Object> model = parser.buildDiagnosisModel(root)
        println JsonOutput.prettyPrint(JsonOutput.toJson(model))
    }
}

ScriptMain.main(this.args as String[])
