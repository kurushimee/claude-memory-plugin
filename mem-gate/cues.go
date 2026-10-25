package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strings"
	"time"
)

const (
	editsEvery     = 5
	transcriptTail = 64 << 10
	callsMax       = 1 << 20
	failedCue      = "this call failed. if the cause was your own slip and not the environment, fix it, then log the general behavior behind it with mem lesson --by self"
	repeatCue      = "this exact call already failed earlier this turn. stop retrying and find the cause first"
	heardCue       = "the user sent a message while you worked. if it points out something you did wrong, first log it with mem lesson --by user as the general behavior behind it, then go on"
)

var editTools = []string{"Edit", "Write", "MultiEdit", "NotebookEdit"}

type trigger struct {
	Slug    string `json:"slug"`
	Project string `json:"project"`
	Tool    string `json:"tool"`
	Pattern string `json:"pattern"`
	Title   string `json:"title"`
	Check   string `json:"check"`
}

// mark is one line of a turn file. The prompt hook writes the start, cues appends the rest.
type mark struct {
	Start   int64  `json:"start,omitempty"`
	Cued    string `json:"cued,omitempty"`
	Failed  string `json:"failed,omitempty"`
	Edited  string `json:"edited,omitempty"`
	Elapsed int    `json:"elapsed,omitempty"`
	Heard   string `json:"heard,omitempty"`
}

type turn struct {
	path    string
	start   time.Time
	cued    map[string]bool
	failed  map[string]bool
	edited  map[string]int
	elapsed int
	heard   map[string]bool
	added   []mark
}

// cues answers every tool call and stays quiet unless something applies: a rule whose trigger fits the call, a
// failed call, a call that already failed this turn, a file edited over and over, a turn running long, or a message
// the user sent while the turn ran.
func cues(p payload) {
	vault := vaultPath()
	if vault == "" {
		return
	}

	t := loadTurn(filepath.Join(vault, ".mem", "turns", p.SessionID+"+"+p.AgentID+".jsonl"))
	text := toolText(p.ToolName, p.ToolInput)
	places := placesOf(p.Cwd, text)
	if path := editedFile(p); path != "" && inScope(vault, normalized(path)) {
		// a note's file name is its title, free text that would fit any trigger, so only the kind of file counts,
		// and the edit happens in the vault whatever folder the session works in
		text = p.ToolName + " " + filepath.Ext(path)
		places = []string{projectOf(vault)}
	}
	logCall(vault, p.ToolName, text, places)
	var out []string

	if p.HookEventName == "PostToolUseFailure" && !p.IsInterrupt {
		out = append(out, t.failure(text))
	}
	if path := editedFile(p); path != "" && p.HookEventName == "PostToolUse" {
		if n := t.edit(path); n%editsEvery == 0 {
			out = append(out, fmt.Sprintf("that's edit number %d of %s this turn. step back and check the approach works before editing it again", n, path))
		}
	}
	if m := t.overtime(); m > 0 {
		out = append(out, fmt.Sprintf("this turn has been going for %d minutes. check that whatever you're waiting on is alive and will end on its own, and that the work is getting closer to done", m))
	}
	if p.AgentID == "" && t.heardUser(p.TranscriptPath) {
		out = append(out, heardCue)
	}
	out = append(out, t.rules(vault, p.ToolName, text, places)...)
	t.save()

	if len(out) == 0 {
		return
	}
	json.NewEncoder(os.Stdout).Encode(map[string]any{
		"hookSpecificOutput": map[string]string{"hookEventName": p.HookEventName, "additionalContext": strings.Join(out, "\n\n")},
	})
}

func loadTurn(path string) *turn {
	t := &turn{path: path, cued: map[string]bool{}, failed: map[string]bool{}, edited: map[string]int{}, heard: map[string]bool{}}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.start = time.Now()
		t.added = append(t.added, mark{Start: t.start.Unix()})
		return t
	}

	for _, line := range bytes.Split(raw, []byte("\n")) {
		var m mark
		if json.Unmarshal(line, &m) != nil {
			continue
		}
		switch {
		case m.Start != 0:
			t.start = time.Unix(m.Start, 0)
		case m.Cued != "":
			t.cued[m.Cued] = true
		case m.Failed != "":
			t.failed[m.Failed] = true
		case m.Edited != "":
			t.edited[m.Edited]++
		case m.Heard != "":
			t.heard[m.Heard] = true
		}
		t.elapsed = max(t.elapsed, m.Elapsed)
	}
	if t.start.IsZero() {
		t.start = time.Now()
	}
	return t
}

// save appends in one write, so tool calls finishing together each add their own lines.
func (t *turn) save() {
	if len(t.added) == 0 {
		return
	}

	var buf bytes.Buffer
	for _, m := range t.added {
		line, _ := json.Marshal(m)
		buf.Write(append(line, '\n'))
	}
	os.MkdirAll(filepath.Dir(t.path), 0o755)
	f, err := os.OpenFile(t.path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return
	}
	defer f.Close()
	f.Write(buf.Bytes())
}

func (t *turn) failure(text string) string {
	again := t.failed[text]
	t.added = append(t.added, mark{Failed: text})
	if again {
		return repeatCue
	}
	return failedCue
}

func (t *turn) edit(path string) int {
	t.edited[path]++
	t.added = append(t.added, mark{Edited: path})
	return t.edited[path]
}

// overtime returns the minute mark the turn just passed, 5, 15, 30 and every 30 after, or 0.
func (t *turn) overtime() int {
	minutes := int(time.Since(t.start).Minutes())
	due := 0
	switch {
	case minutes >= 30:
		due = minutes / 30 * 30
	case minutes >= 15:
		due = 15
	case minutes >= 5:
		due = 5
	}
	if due <= t.elapsed {
		return 0
	}

	t.added = append(t.added, mark{Elapsed: due})
	return due
}

// heardUser finds a message the user typed while this turn ran. The app adds those to the transcript as
// queued_command attachments and fires no prompt hook for them.
func (t *turn) heardUser(transcript string) bool {
	f, err := os.Open(transcript)
	if err != nil {
		return false
	}
	defer f.Close()

	if info, err := f.Stat(); err == nil && info.Size() > transcriptTail {
		f.Seek(-transcriptTail, io.SeekEnd)
	}
	tail, err := io.ReadAll(f)
	if err != nil {
		return false
	}

	var entry struct {
		Attachment struct {
			Type      string `json:"type"`
			Timestamp string `json:"timestamp"`
			Origin    struct {
				Kind string `json:"kind"`
			} `json:"origin"`
		} `json:"attachment"`
	}

	found := false
	for _, line := range bytes.Split(tail, []byte("\n")) {
		if !bytes.Contains(line, []byte(`"queued_command"`)) || json.Unmarshal(line, &entry) != nil {
			continue
		}
		a := entry.Attachment
		at, err := time.Parse(time.RFC3339Nano, a.Timestamp)
		if a.Type != "queued_command" || a.Origin.Kind != "human" || err != nil || at.Before(t.start) || t.heard[a.Timestamp] {
			continue
		}
		t.heard[a.Timestamp] = true
		t.added = append(t.added, mark{Heard: a.Timestamp})
		found = true
	}
	return found
}

// placesOf is the session's project and the folders the call's paths lead into, where a rule's scope has to reach.
func placesOf(cwd, text string) []string {
	places := []string{projectOf(cwd)}
	for _, path := range pathsIn(text) {
		places = append(places, projectOf(path))
	}
	return places
}

// logCall keeps the recent calls, so mem can show what a trigger would fit before it goes in. Past callsMax the
// file moves to calls.old.jsonl, which keeps the log between one and two of those long.
func logCall(vault, tool, text string, places []string) {
	path := filepath.Join(vault, ".mem", "calls.jsonl")
	if info, err := os.Stat(path); err == nil && info.Size() > callsMax {
		os.Rename(path, filepath.Join(vault, ".mem", "calls.old.jsonl"))
	}

	line, _ := json.Marshal(map[string]any{"tool": tool, "text": text, "places": places})
	f, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return
	}
	defer f.Close()
	f.Write(append(line, '\n'))
}

// rules brings up each rule whose trigger fits the call once per turn, where the rule's scope reaches one of the
// call's places.
func (t *turn) rules(vault, tool, text string, places []string) []string {
	raw, err := os.ReadFile(filepath.Join(vault, ".mem", "triggers.json"))
	var triggers []trigger
	if err != nil || json.Unmarshal(raw, &triggers) != nil {
		return nil
	}

	var out []string
	for _, tr := range triggers {
		if t.cued[tr.Slug] || !slices.ContainsFunc(places, func(place string) bool { return inScope(tr.Project, place) }) {
			continue
		}
		if !matches("^(?:"+tr.Tool+")$", tool) || !matches(tr.Pattern, text) {
			continue
		}

		t.cued[tr.Slug] = true
		t.added = append(t.added, mark{Cued: tr.Slug})
		cue := "a rule fits this call, " + tr.Title
		if tr.Check != "" {
			cue += "\ncheck " + tr.Check
		}
		out = append(out, cue)
	}
	return out
}

func matches(pattern, text string) bool {
	re, err := regexp.Compile("(?i)" + pattern)
	return err == nil && re.MatchString(text)
}

func editedFile(p payload) string {
	if !slices.Contains(editTools, p.ToolName) {
		return ""
	}
	for _, k := range []string{"file_path", "notebook_path"} {
		if v, ok := p.ToolInput[k].(string); ok {
			return v
		}
	}
	return ""
}
