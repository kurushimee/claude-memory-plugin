// mem-gate answers the memory plugin's tool call hooks in a few milliseconds. On its own it hands the call to
// `mem recall` only when a path in it leads into a folder that has notes the session has not reached yet, and as
// `mem-gate cues` it puts the cues of cues.go next to the call's result.
package main

import (
	"bytes"
	"encoding/json"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"slices"
	"strings"
	"unicode"
	"unicode/utf8"
)

var (
	toolKeys = []string{"file_path", "path", "pattern", "command", "glob", "notebook_path"}
	memCall  = regexp.MustCompile(`\bmem(\.exe)? |memory_`)
	pathAt   = regexp.MustCompile("^(?:[A-Za-z]:[\\\\/]|/[a-zA-Z]/)[^\\s\\v\\pZ\"'`|;&<>()]*")
)

type payload struct {
	HookEventName  string         `json:"hook_event_name"`
	SessionID      string         `json:"session_id"`
	AgentID        string         `json:"agent_id"`
	Cwd            string         `json:"cwd"`
	TranscriptPath string         `json:"transcript_path"`
	ToolName       string         `json:"tool_name"`
	ToolInput      map[string]any `json:"tool_input"`
	IsInterrupt    bool           `json:"is_interrupt"`
}

func main() {
	raw, err := io.ReadAll(os.Stdin)
	if err != nil {
		return
	}

	var p payload
	if json.Unmarshal(raw, &p) != nil {
		return
	}
	if len(os.Args) > 1 && os.Args[1] == "cues" {
		cues(p)
		return
	}
	if !mayBringNotes(p) {
		return
	}

	recall := exec.Command("mem", "recall")
	recall.Stdin = bytes.NewReader(raw)
	recall.Stdout = os.Stdout
	recall.Run()
}

func mayBringNotes(p payload) bool {
	// the app hands an async hook's output from a subagent's call to the main session, which never went there
	if p.AgentID != "" {
		return false
	}

	vault := vaultPath()
	text := toolText(p.ToolName, p.ToolInput)
	if vault == "" || touchesMemory(text, vault) {
		return false
	}

	scopes, ok := lines(filepath.Join(vault, ".mem", "scopes"))
	if !ok {
		return true
	}
	reached, _ := lines(filepath.Join(vault, ".mem", "reached", p.SessionID+"+"+p.AgentID))
	project := projectOf(p.Cwd)

	for _, path := range pathsIn(text) {
		place := projectOf(path)
		if place == project || place == "global" {
			continue
		}
		for _, scope := range scopes {
			if inScope(scope, place) && !inScope(scope, project) && !slices.Contains(reached, scope) {
				return true
			}
		}
	}
	return false
}

func toolText(name string, input map[string]any) string {
	parts := []string{name}
	for _, k := range toolKeys {
		if v, ok := input[k].(string); ok {
			parts = append(parts, firstRunes(v, 300))
		}
	}
	return strings.Join(parts, " ")
}

func firstRunes(s string, n int) string {
	for i := range s {
		if n == 0 {
			return s[:i]
		}
		n--
	}
	return s
}

func touchesMemory(text, vault string) bool {
	if memCall.MatchString(text) {
		return true
	}
	return slices.ContainsFunc(pathsIn(text), func(p string) bool { return inScope(vault, p) })
}

// pathsIn matches vault.paths_in. RE2 has no lookbehind, so it tries a match at every rune and checks
// the rune before by hand, which also keeps Python's leftmost, non-overlapping order.
func pathsIn(text string) []string {
	var out []string
	for i := 0; i < len(text); {
		if m := pathAt.FindString(text[i:]); m != "" && freeBefore(text[:i], m[0] == '/') {
			out = append(out, normalized(m))
			i += len(m)
			continue
		}
		_, size := utf8.DecodeRuneInString(text[i:])
		i += size
	}
	return out
}

func freeBefore(before string, gitBash bool) bool {
	if before == "" {
		return true
	}
	r, _ := utf8.DecodeLastRuneInString(before)
	if gitBash {
		return !(unicode.IsLetter(r) || unicode.IsNumber(r) || strings.ContainsRune("_.~/-", r))
	}
	return !(r < utf8.RuneSelf && unicode.IsLetter(r))
}

func normalized(p string) string {
	p = strings.ReplaceAll(p, `\`, "/")
	if p[0] == '/' {
		return strings.ToUpper(p[1:2]) + ":" + p[2:]
	}
	return p
}

func projectOf(dir string) string {
	if dir == "" || strings.Contains(dir, "scratch-workspaces") {
		return "global"
	}

	p := filepath.Clean(dir)
	for d := p; ; d = filepath.Dir(d) {
		if _, err := os.Stat(filepath.Join(d, ".git")); err == nil {
			return filepath.ToSlash(d)
		}
		if filepath.Dir(d) == d {
			break
		}
	}

	home, _ := os.UserHomeDir()
	if strings.EqualFold(p, home) || filepath.Dir(p) == p {
		return "global"
	}
	return filepath.ToSlash(p)
}

func inScope(noteProject, project string) bool {
	if noteProject == "global" {
		return true
	}
	return strings.HasPrefix(slashed(project), slashed(noteProject))
}

func slashed(p string) string {
	return strings.ToLower(strings.TrimRight(p, "/")) + "/"
}

func vaultPath() string {
	if v := os.Getenv("MEM_VAULT"); v != "" {
		return filepath.ToSlash(v)
	}
	home, _ := os.UserHomeDir()
	raw, err := os.ReadFile(filepath.Join(home, ".config", "mem", "vault"))
	if err != nil {
		return ""
	}
	return filepath.ToSlash(strings.TrimSpace(string(raw)))
}

func lines(path string) ([]string, bool) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, false
	}
	return strings.FieldsFunc(string(raw), func(r rune) bool { return r == '\n' }), true
}
