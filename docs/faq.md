# Frequently asked questions

<!--
Adding a question: copy a block below. The first line is the question, and
the indented lines under it are the answer (4 spaces). `???` renders
collapsed; `???+` renders expanded. Put it under the section it belongs to.
-->

## Getting set up

??? question "Where is my data stored?"
    By default it's in `~/.local/share/tavla/`, a normal git repo. Run
    `tavla init --content-dir PATH` to put it elsewhere, or see
    [Where tavla looks](guide/content-repo.md#where-tavla-looks) for how
    tavla finds it.

??? question "How do I use tavla on two computers?"
    Push the content repo to a **private** remote and pull on the other
    machine. tavla never pushes by itself. See
    [Syncing between machines](guide/content-repo.md#syncing-between-machines).

??? question "Can I try tavla without creating my own content repo?"
    Yes. `tv demo` sets up a separate playground repo with example projects
    and tells you how to point tavla at it. Every command works there,
    including the ones that change things. See the
    [several-projects example](examples/several-projects.md).

??? question "Is there a difference between `tavla` and `tv`?"
    No. `tv` is just a shorter name for the same program.

## Everyday use

<a id="my-tag-disappeared"></a>

??? question "My `#tag` disappeared when I captured an idea."
    Your shell probably treated ` #` as the start of a comment. Bash does this
    by default, and so does zsh with `setopt interactive_comments`. Quote the
    text:

    ```sh
    tv capture "look into parallel tempering #mcmc"
    ```

??? question "Why doesn't my task show up in `tv next`?"
    Check each of these:

    - It's **waiting** on an unfinished dependency. `tv task show ID` lists
      what it's after.
    - Its status is `blocked` or `done`.
    - Its project (or a parent project) is `paused`, `done` or `archived`.
    - It's past the top 10. Use `tv next -n 0` to see everything.
    - You filtered with `--priority` or `-p`.

??? question "Should this be a goal, a task or a subtask?"
    A **task** is something you'd want to see on its own in `next`. A
    **subtask** only makes sense while you're working on its task. A
    **goal** is an outcome that needs several tasks. See
    [Organising work](guide/organising-work.md#the-hierarchy).

??? question "tavla says my id is ambiguous."
    More than one thing matches what you typed, and tavla lists the
    candidates. Type a bit more, or the full id.

??? question "How do I rename something?"
    Run `tv task edit ID` (or `goal`/`project edit`) with no options and
    change the `id:` or title line in your editor. Tasks that pointed at the
    old id are updated automatically.

??? question "How do I undo a mistake?"
    Every change is a git commit. `tavla undo` reverts the last one (as a
    new commit, so nothing is lost); run it again to go further back, or
    `tavla undo -n` to see what it would undo first.

??? question "How do I move a task to another project?"
    Move its file into the other project's `tasks/` folder and commit.
    Remove its `goal:` first if that goal belongs to the old project. Links
    use ids, not paths, so nothing else needs to change.

??? question "How do I make a subproject, or move a project under another?"
    Use `tv project add NAME -p PARENT` to create one, and
    `tv project edit ID -p PARENT` to move an existing project under
    another. `-p none` moves it back to the top level. See
    [Subprojects](guide/organising-work.md#subprojects).

??? question "Can I turn a goal into a task, or an idea into a task?"
    Yes: use `tv goal to-task ID` and `tv idea promote REF -g GOAL`. A goal
    can only be converted once it has no tasks, and only within the same
    project.

## Editing files

??? question "Can I edit the files by hand?"
    Yes. That's the point of plain text. Commit your edits yourself
    afterwards. If you'd rather have tavla validate and commit for you, open
    the file with `tv task edit ID` instead.

    Afterwards, run `tv check` to catch anything tavla would have refused:
    files that don't load, duplicate ids, unknown goals or dependencies, and
    cycles.

    One exception: changing the `project:` line in a file you opened yourself
    does not move it, because the file's folder decides its project.
    `tv check` lists such files and `tv check --fix` moves them. Or use
    `tv goal edit ID --project P` in the first place.

??? question "What happens if I save an invalid file in `tv ... edit`?"
    tavla reports the problem (for example an unknown goal, an unknown
    dependency or a cycle) and restores the previous version, so nothing
    broken gets committed.

??? question "I typed `01.10.2026` in a file and it changed to `2026-10-01`."
    That's intended. Files always store ISO dates, and tavla converts
    day-first dates when you save through `edit`.

## Upgrading

??? question "How do I update tavla?"
    Run `tv update`, or `tv update --check` to see what's new first. It
    fast-forwards the clone you installed from to `origin/main`. See
    [Updating tavla](getting-started.md#updating-tavla).

??? question "`tv update` says it can't update itself."
    `update` only works when tavla runs from a git clone (the
    `uv tool install --editable .` install in the README). If you installed
    it some other way, reinstall from a clone. If it refuses because of
    uncommitted changes, another branch or diverged commits, sort that out
    in the clone with git first.

??? question "tavla says my content uses an older layout."
    Run `tavla migrate --dry-run` to see the plan, then `tavla migrate`. It's
    a single commit, so `tavla undo` reverts it. The
    repo must have no uncommitted changes first.
