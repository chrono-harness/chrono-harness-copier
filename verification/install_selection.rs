use vstd::prelude::*;

verus! {

#[derive(Clone, Copy)]
enum Selection { Disabled, Configured, Override }

fn selection(disabled: bool, has_override: bool) -> (action: Selection)
    ensures (action is Disabled) == disabled,
        (action is Configured) == (!disabled && !has_override),
        (action is Override) == (!disabled && has_override),
{
    if disabled { Selection::Disabled }
    else if has_override { Selection::Override }
    else { Selection::Configured }
}

#[derive(Clone, Copy)]
enum Platform { Linux, Mac, Unsupported }

fn platform(linux: bool, mac: bool) -> (p: Platform)
    requires !(linux && mac),
    ensures (p is Linux) == linux, (p is Mac) == mac, (p is Unsupported) == (!linux && !mac),
{
    if linux { Platform::Linux } else if mac { Platform::Mac } else { Platform::Unsupported }
}

struct PlatformFields {
    key: &'static str,
    other: &'static str,
    asset: &'static str,
    seed: u8,
    linux: u8,
    macos: u8,
}

// Arguments 2 and 3 are Linux/macOS seed digests at startup, and current/other
// checksums when serializing the host-independent selection.
fn platform_fields(p: Platform) -> (f: Option<PlatformFields>)
    ensures
        f.is_some() == !(p is Unsupported),
        p is Linux ==> f.unwrap().key@ == "linux-x64"@ && f.unwrap().other@ == "macos-arm64"@
            && f.unwrap().asset@ == "linux-x86_64"@ && f.unwrap().seed == 2
            && f.unwrap().linux == 2 && f.unwrap().macos == 3,
        p is Mac ==> f.unwrap().key@ == "macos-arm64"@ && f.unwrap().other@ == "linux-x64"@
            && f.unwrap().asset@ == "macos-aarch64"@ && f.unwrap().seed == 3
            && f.unwrap().linux == 3 && f.unwrap().macos == 2,
{
    match p {
        Platform::Linux => Some(PlatformFields { key: "linux-x64", other: "macos-arm64",
            asset: "linux-x86_64", seed: 2, linux: 2, macos: 3 }),
        Platform::Mac => Some(PlatformFields { key: "macos-arm64", other: "linux-x64",
            asset: "macos-aarch64", seed: 3, linux: 3, macos: 2 }),
        Platform::Unsupported => None,
    }
}

#[derive(Clone, Copy)]
enum Page { Advance, Finish, Reject }

fn page(next: bool, done: bool) -> (action: Page)
    requires !(next && done),
    ensures (action is Advance) == next, (action is Finish) == done,
        (action is Reject) == (!next && !done),
{
    if next { Page::Advance } else if done { Page::Finish } else { Page::Reject }
}

#[derive(Clone, Copy)]
enum Receipt { Retain, Replace, Withdraw }

fn receipt(verified: bool, dynamic: bool) -> (action: Receipt)
    ensures (action is Retain) == !verified, (action is Replace) == (verified && dynamic),
        (action is Withdraw) == (verified && !dynamic),
{
    if !verified { Receipt::Retain } else if dynamic { Receipt::Replace } else { Receipt::Withdraw }
}

#[derive(Clone, Copy)]
enum Override { Use, Unsafe, Invalid }

fn channel(named: bool, safe: bool, exact: bool) -> (out: Override)
    ensures (out is Use) == (named || (safe && exact)),
        (out is Unsafe) == (!named && !safe),
        (out is Invalid) == (!named && safe && !exact),
{
    if named { Override::Use } else if !safe { Override::Unsafe }
    else if exact { Override::Use } else { Override::Invalid }
}

fn needs_resolver(pinned: bool) -> (dynamic: bool)
    ensures dynamic == !pinned,
{ !pinned }

// Independently state each user-visible boundary, including override of a disabled tool.
fn boundary_expectations() {
    let linux = platform_fields(Platform::Linux).unwrap();
    let mac = platform_fields(Platform::Mac).unwrap();
    assert(linux.seed == 2 && linux.linux == 2 && linux.macos == 3);
    assert(mac.seed == 3 && mac.linux == 3 && mac.macos == 2);
    let stable = channel(true, true, false);
    let tag = channel(false, true, true);
    let invalid = channel(false, true, false);
    let unsafe_text = channel(false, false, true);
    let fixed = needs_resolver(true);
    let floating = needs_resolver(false);
    assert(stable is Use && tag is Use && invalid is Invalid && unsafe_text is Unsafe);
    assert(!fixed && floating);
    let observed = selection(true, false);
    assert(observed is Disabled);
    let observed = selection(true, true);
    assert(observed is Disabled);
    let observed = selection(false, false);
    assert(observed is Configured);
    let observed = selection(false, true);
    assert(observed is Override);
    let observed = platform(true, false);
    assert(observed is Linux);
    let observed = platform(false, true);
    assert(observed is Mac);
    let observed = platform(false, false);
    assert(observed is Unsupported);
    let observed = page(true, false);
    assert(observed is Advance);
    let observed = page(false, true);
    assert(observed is Finish);
    let observed = page(false, false);
    assert(observed is Reject);
    let observed = receipt(false, true);
    assert(observed is Retain);
    let observed = receipt(false, false);
    assert(observed is Retain);
    let observed = receipt(true, true);
    assert(observed is Replace);
    let observed = receipt(true, false);
    assert(observed is Withdraw);
}
}

#[verifier::external]
pub fn emit() {
    boundary_expectations();
    println!("# Generated by verification/install_selection.rs. Used before any tool is installed.");
    // Lexical observations come from POSIX case and the same anchored regular expression as the CLI.
    println!(r#"validate_override() {{
    case "$1" in
        stable|preview) observed=named ;;
        *[!A-Za-z0-9.-]*|'') observed=unsafe ;;
        *)
            if printf '%s\n' "$1" | grep -Eq '^v[0-9]+[.][0-9]+[.][0-9]+(-[A-Za-z0-9-]+([.][A-Za-z0-9-]+)*)?$'; then
                observed=exact
            else
                observed=invalid
            fi ;;
    esac
    case "$observed" in"#);
    for (name, named, safe, exact) in [("named",true,true,false), ("unsafe",false,false,false),
        ("exact",false,true,true), ("invalid",false,true,false)] {
        let action = match channel(named, safe, exact) {
            Override::Use => "return 0",
            Override::Unsafe => "fail 'Invalid CHRONO_TOOL_CHANNEL.'",
            Override::Invalid => "fail 'CHRONO_TOOL_CHANNEL expects stable, preview or an exact v tag.'",
        };
        println!("        {name}) {action} ;;");
    }
    println!("    esac\n}}");
    // The Shell/mise boundary supplies the quoted disabled-tool observation and override presence.
    println!(r#"select_tool() {{
    case "$disabled" in *\"http:$1\"*) disabled_tool=1 ;; *) disabled_tool=0 ;; esac
    case "$disabled_tool:${{CHRONO_TOOL_CHANNEL+x}}" in"#);
    for disabled in [false,true] {
        for supplied in [false,true] {
            let command = match selection(disabled, supplied) {
                Selection::Disabled => "return 1",
                Selection::Configured => "selector=$2",
                Selection::Override => "selector=$CHRONO_TOOL_CHANNEL",
            };
            println!("        {}:{}) {command} ;;", u8::from(disabled), if supplied {"x"} else {""});
        }
    }
    println!("    esac\n    case \"$selector\" in");
    for (pattern, is_pinned) in [("pinned",true), ("*",false)] {
        println!("        {pattern}) dynamic={} ;;", u8::from(needs_resolver(is_pinned)));
    }
    println!("    esac\n}}");
    println!("select_platform() {{\n    case \"$1\" in");
    for (name, linux, mac) in [("Linux-x86_64",true,false), ("Darwin-arm64",false,true), ("*",false,false)] {
        match platform_fields(platform(linux, mac)) {
            Some(f) => println!("        {name}) platform={}; asset={}; seed_sha=${}; other_platform={} ;;",
                f.key, f.asset, f.seed, f.other),
            None => println!("        {name}) fail 'Unsupported installation platform.' ;;"),
        }
    }
    println!("    esac\n}}");
    println!("order_checksums() {{\n    case \"$1\" in");
    for kind in [Platform::Linux, Platform::Mac] {
        let f=platform_fields(kind).unwrap();
        println!("        {}) linux=${}; macos=${} ;;", f.key, f.linux, f.macos);
    }
    println!("    esac\n}}");
    // The resolver's original stdout is the discriminator. Failure from the resolver is propagated by its caller.
    println!("more_release_pages() {{\n    case \"$1\" in");
    for (state, next, done) in [("next",true,false), ("done",false,true), ("*",false,false)] {
        let result=match page(next, done) {
            Page::Advance => "return 0",
            Page::Finish => "return 1",
            Page::Reject => "fail \"Unexpected release page state: $1\"",
        };
        println!("        {state}) {result} ;;");
    }
    println!("    esac\n}}");
    println!("accept_checksum() {{\n    if [ \"$1\" = \"$2\" ]; then");
    for valid in [true, false] {
        match receipt(valid, false) {
            Receipt::Retain => println!("        fail \"SHA-256 mismatch for $3\""),
            Receipt::Replace | Receipt::Withdraw => println!("        return 0"),
        }
        if valid { println!("    else"); }
    }
    println!("    fi\n}}");
    println!(r#"publish_selection() {{
    # $1 is the staged selection, $2 the mv destination, $3 the file to remove.
    # Installation, digest and path failures keep the previous file by exiting before this call.
    if [ -s "$1" ]; then"#);
    for dynamic in [true,false] {
        match receipt(true,dynamic) {
            Receipt::Replace => println!("        mv -f \"$1\" \"$2\""),
            Receipt::Withdraw => println!("        rm -f \"$3\""),
            Receipt::Retain => (),
        }
        if dynamic { println!("    else"); }
    }
    println!("    fi\n}}");
}
