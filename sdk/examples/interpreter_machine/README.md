# Interpreter Machine

A single-state FlatMachine that interprets user statements and builds a collaborative
`INTERPRETATIONS.md` document over time.

## What it does

You give it a statement — an idea, a complaint, a question, a half-formed thought.
The machine:

1. **Interprets** the statement using its training knowledge and reasoning
2. **Explores** local files for context (what project is this? what's around?)
3. **Reads** `INTERPRETATIONS.md` to see what's already been interpreted
4. **Compares** its interpretation with existing entries
5. **Edits** the file to insert its interpretation near the most similar existing ones

Over time, `INTERPRETATIONS.md` becomes a rich, multi-perspective document where
related interpretations cluster together and contradictions coexist.

## Usage

```bash
# Basic — interpret a statement
./run.sh "I would like to simplify the flatmachines interface."

# With a specific working directory
./run.sh -w ~/code/myproject "What if state machines are the wrong abstraction?"

# Using local SDK sources
./run.sh --local "The config files are doing too much."
```

The statement can be anything:
- A feature request: `"We need better error messages"`
- A philosophical question: `"What if agents don't need state?"`
- A complaint: `"The YAML is too verbose"`
- A vague feeling: `"Something about the hooks feels wrong"`

## Tools

The interpreter agent has 4 tools:

| Tool | Purpose |
|------|---------|
| **Bash** | Explore the filesystem, run commands for context |
| **Read** | Read files to understand the environment |
| **Write** | Create INTERPRETATIONS.md if it doesn't exist |
| **Edit** | Surgically insert interpretations into the document |

## The INTERPRETATIONS.md Format

Each interpretation entry looks like:

```markdown
### [short title]
> Original statement: "the user's statement"

[2-5 paragraphs of interpretation, grounded in context]

*Connections: [links to related existing interpretations]*
```

Entries are grouped by theme. New themes emerge as needed. Nothing is ever deleted.

## Architecture

This is a single-state FlatMachine (`start → interpret → done`) using the
`claude-code` agent adapter. The entire logic lives in the system prompt —
the machine just routes the statement to the agent and captures the result.
