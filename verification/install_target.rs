use vstd::prelude::*;

verus! {

enum Target {
    Harness,
    State,
    Selection,
    Legacy,
    Versions,
    Entry,
}

enum Rejection {
    Directory,
    File,
    Extra,
}

impl Target {
    spec fn permits(&self, link: bool, present: bool, expected: bool) -> bool {
        match self {
            Target::Entry => expected || (!link && !present),
            _ => !link && (!present || expected),
        }
    }

    spec fn rejection(&self) -> Rejection {
        match self {
            Target::Harness | Target::State | Target::Selection => Rejection::Directory,
            Target::Legacy | Target::Versions => Rejection::File,
            Target::Entry => Rejection::Extra,
        }
    }

    fn decide(&self, link: bool, present: bool, expected: bool) -> (result: Option<Rejection>)
        ensures
            result == if self.permits(link, present, expected) {
                None
            } else {
                Some(self.rejection())
            },
    {
        match self {
            Target::Entry => {
                if !expected && (present || link) { Some(Rejection::Extra) } else { None }
            },
            Target::Harness | Target::State | Target::Selection => {
                if link || (present && !expected) { Some(Rejection::Directory) } else { None }
            },
            Target::Legacy | Target::Versions => {
                if link || (present && !expected) { Some(Rejection::File) } else { None }
            },
        }
    }
}

// The adapter visits the fixed paths once, then streams the ordered glob expansion.
// Rejection exits the installer, so the earliest rejecting visit supplies the error.
fn target_at(index: u8) -> (target: Target)
    requires index < 6,
    ensures
        index == 0 ==> target == Target::Harness,
        index == 1 ==> target == Target::State,
        index == 2 ==> target == Target::Selection,
        index == 3 ==> target == Target::Legacy,
        index == 4 ==> target == Target::Versions,
        index == 5 ==> target == Target::Entry,
{
    match index {
        0 => Target::Harness,
        1 => Target::State,
        2 => Target::Selection,
        3 => Target::Legacy,
        4 => Target::Versions,
        _ => Target::Entry,
    }
}

fn boundary_expectations() {
    let missing = target_at(2).decide(false, false, false);
    let wrong_state = target_at(1).decide(false, true, false);
    let linked_harness = target_at(0).decide(true, true, true);
    let linked_legacy = target_at(3).decide(true, true, true);
    let dangling_versions = target_at(4).decide(true, false, false);
    let versions = target_at(5).decide(false, true, true);
    let extra_directory = target_at(5).decide(false, true, false);
    let dangling_extra = target_at(5).decide(true, false, false);
    let unmatched_glob = target_at(5).decide(false, false, false);
    assert(missing is None);
    assert(wrong_state == Some(Rejection::Directory));
    assert(linked_harness == Some(Rejection::Directory));
    assert(linked_legacy == Some(Rejection::File));
    assert(dangling_versions == Some(Rejection::File));
    assert(versions is None);
    assert(extra_directory == Some(Rejection::Extra));
    assert(dangling_extra == Some(Rejection::Extra));
    assert(unmatched_glob is None);
}

} // verus!

#[verifier::external]
fn main() {
    boundary_expectations();
    println!("# Generated from verification/install_target.rs during Copier development.");
    print!(r#"validate_installation_path() {{
    target_path=$1
    target_role=$2
    shift 2
    target_flags=
    for target_test in -L -e; do
        if test "$target_test" "$target_path"; then
            target_flags=${{target_flags}}1
        else
            target_flags=${{target_flags}}0
        fi
    done
    if test "$@"; then target_flags=${{target_flags}}1; else target_flags=${{target_flags}}0; fi
    case "$target_role:$target_flags" in
"#);
    for (target, role) in [(Target::Selection, "directory"), (Target::Versions, "file"), (Target::Entry, "entry")] {
        for link in [false, true] {
            for present in [false, true] {
                for expected in [false, true] {
                    if let Some(rejection) = target.decide(link, present, expected) {
                        let reason = match rejection {
                            Rejection::Directory => "Expected an installation state directory",
                            Rejection::File => "Expected a regular installation selection",
                            Rejection::Extra => "Unexpected installation data entry",
                        };
                        println!("        {role}:{}{}{}) fail \"{reason}: $target_path\" ;;",
                                 u8::from(link), u8::from(present), u8::from(expected));
                    }
                }
            }
        }
    }
    println!("    esac\n}}\nvalidate_target() {{");
    for index in 0..6 {
        let target = target_at(index);
        let path = match target {
            Target::Harness => "$PWD/.chrono-harness",
            Target::State => "$state",
            Target::Selection => "$selection",
            Target::Legacy => "$legacy",
            Target::Versions => "$resolved",
            Target::Entry => {
                print!(r#"    for entry in "$selection"/* "$selection"/.[!.]* "$selection"/..?*; do
        validate_installation_path "$entry" entry "$entry" = "$resolved"
    done
"#);
                continue;
            },
        };
        let (role, test) = match target {
            Target::Harness | Target::State | Target::Selection => ("directory", "-d"),
            Target::Legacy | Target::Versions => ("file", "-f"),
            Target::Entry => unreachable!(),
        };
        println!(r#"    validate_installation_path "{path}" {role} {test} "{path}""#);
    }
    println!("}}");
}
