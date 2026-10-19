# Cooooost

Quality-preserving context checkpointing for AI agents. The project contains a portable Agent Skill and a dependency-free Python CLI.

## Installation

```bash
git clone https://github.com/skaletun/Cooooost.git
mkdir -p ~/.agents/skills/cooooost
cp Cooooost/SKILL.md ~/.agents/skills/cooooost/SKILL.md
```

Install the skill in your particular agent's supported skill directory. The CLI is opt-in:

```bash
python Cooooost/scripts/cooooost.py init --project .
python Cooooost/scripts/cooooost.py update --project . --goal "Ship verified changes" --next "Run tests"
python Cooooost/scripts/cooooost.py checkpoint --project .
python Cooooost/scripts/cooooost.py daemon --project . --interval-min 7 --interval-max 13
```

The daemon snapshots only the state explicitly written to disk; it does not force AI model compaction. It cannot change provider usage limits. The raw task evidence must be retained separately. Quality checks remain mandatory.

Run tests with `python -m unittest discover -s tests -v`.
