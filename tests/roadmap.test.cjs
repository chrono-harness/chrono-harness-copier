const test = require('node:test')
const assert = require('node:assert/strict')
const sync = require('../.github/roadmap.cjs')

// Each response is supplied by the test scenario. The Rust product owns the decisions.
function mockRoadmap(t) {
  const requests = []
  t.mock.method(require('node:child_process'), 'execFileSync', (program, args, options) => {
    assert.equal(program, 'chrono-host-release')
    assert.equal(options.encoding, 'utf8')
    const expected = requests.shift()
    assert.deepEqual(args, [expected.command])
    const input = JSON.parse(options.input)
    assert.deepEqual(input, expected.input)
    if (expected.error) throw expected.error
    return JSON.stringify(expected.output)
  })
  t.after(() => assert.deepEqual(requests, []))
  return (input, output, error, command = 'roadmap-v1') => requests.push({input, output, error, command})
}

test('new work, release publication, closing and reopening reconcile against current GitHub state', async t => {
  const reply = mockRoadmap(t)
  const items = [{number: 1, state: 'open'}, {number: 2, state: 'open', pull_request: {}}]
  const milestones = []
  const releases = []
  const writes = []
  const issues = {
    listMilestones: () => milestones,
    listForRepo: () => items.filter(i => !i.milestone && i.state === 'open'),
    createMilestone: ({title}) => {
      const data = {number: milestones.length + 1, title, state: 'open', description: ''}
      writes.push(['create', title])
      milestones.push(data)
      return {data}
    },
    getMilestone: ({milestone_number}) => {
      const row = milestones.find(m => m.number === milestone_number)
      return {data: {...row, open_issues: items.filter(i => i.milestone === row.number && i.state === 'open').length}}
    },
    update: ({issue_number, milestone}) => {
      writes.push(['assign', issue_number])
      items.find(i => i.number === issue_number).milestone = milestone
    },
    updateMilestone: ({milestone_number, description, state}) => {
      Object.assign(milestones.find(m => m.number === milestone_number), {state, description})
      writes.push(['update', milestone_number])
    },
  }
  const github = {rest: {issues, repos: {listReleases: () => releases}}, paginate: async (fn, args) => [...fn(args)]}
  const defaults = {version: '1.2.0'}
  const run = (selected, numbers, state, plan = defaults, version) => {
    const snapshots = releases.map(({draft, published_at}) => JSON.parse(JSON.stringify({draft, published_at})))
    reply({operation: 'published', releases: snapshots}, selected)
    if (version) {
      const tags = releases.map(({tag_name, draft, prerelease, published_at}) =>
        JSON.parse(JSON.stringify({tag_name, draft, prerelease, published_at})))
      reply(tags, version.latest ? 'v' + version.latest : null, undefined, 'template-latest-stable-v1')
      reply({floor: plan.version, latest: version.latest}, version.target, undefined, 'template-next-version-v1')
    }
    if (numbers !== null) {
      const rows = issues.listForRepo().map(({number, state, pull_request, milestone}) =>
        JSON.parse(JSON.stringify({number, state, pull_request, milestone})))
      reply({operation: 'unassigned', issues: rows}, numbers)
    }
    if (state) {
      const milestone = milestones.find(m => m.title === 'v1.2.0')
      const lines = ['测试版 [v1.2.0-alpha.1](https://example.org/preview)']
      if (state.final) lines.push('正式版 [v1.2.0](https://example.org/stable)')
      reply({operation: 'release-block', milestone: milestone.number, original: milestone.description, lines},
        state.final ? '原样交还的正式版正文' : '保留宿主计划。 v1.2.0-alpha.1', state.error)
      if (!state.error) reply({operation: 'milestone', final_release: state.final, open_issues: state.open}, state.result)
    }
    return sync(github, {repo: {owner: 'a', repo: 'b'}, payload: {}}, plan)
  }
  await run([], [1], null, null)
  assert.equal(milestones[0].title, 'Backlog')
  assert.equal(items[0].milestone, 1)
  assert.equal(items[1].milestone, undefined)
  items.push({number: 3, state: 'open'})
  await run([], [3])
  const target = milestones.find(m => m.title === 'v1.2.0')
  target.description = '保留宿主计划。'
  assert.equal(items[2].milestone, target.number)
  assert.equal(items[0].milestone, 1)
  releases.push({tag_name: 'v1.2.0-alpha.1', draft: false, published_at: '2025-01-01', prerelease: true, html_url: 'https://example.org/preview'})
  releases.push({tag_name: 'v1.2.0', draft: true})
  await run([0], [], {final:false, open:1, result:'open'})
  assert.match(target.description, /保留宿主计划。/)
  assert.match(target.description, /v1\.2\.0-alpha\.1/)
  assert.doesNotMatch(target.description, /正式版/)
  releases.push({tag_name: 'v1.2.0', draft: false, published_at: '2025-02-01', prerelease: false, html_url: 'https://example.org/stable'})
  items.push({number: 4, state: 'open'})
  await run([0, 2], [4], {final:true, open:1, result:'open'})
  assert.equal(items[3].milestone, 1)
  assert.equal(target.state, 'open')
  assert.equal(target.description, '原样交还的正式版正文')
  items[2].state = 'closed'
  await run([0, 2], [], {final:true, open:0, result:'closed'})
  assert.equal(target.state, 'closed')
  writes.length = 0
  await run([0, 2], [], {final:true, open:0, result:'closed'})
  assert.deepEqual(writes, [])
  items[2].state = 'open'
  await run([0, 2], [], {final:true, open:1, result:'open'})
  assert.equal(target.state, 'open')
  items.push({number: 5, state: 'open'})
  const rolling = {kind: 'copier', version: '1.2.0', version_policy: 'next_patch'}
  await run([0, 2], [5], {final:true, open:1, result:'open'}, rolling, {latest:'1.2.0', target:'1.2.1'})
  assert.equal(items.at(-1).milestone, milestones.find(m => m.title === 'v1.2.1').number)
  items.push({number: 6, state: 'open'})
  await run([0, 2], [6], {final:true, open:1, result:'open'}, {...rolling, version: '2.0.0'}, {latest:'1.2.0', target:'2.0.0'})
  assert.equal(items.at(-1).milestone, milestones.find(m => m.title === 'v2.0.0').number)
  target.description = '<!-- chrono-harness release -->未完的原文'
  writes.length = 0
  const error = new Error('Incomplete release block in milestone ' + target.number)
  await assert.rejects(run([0, 2], [], {final:true, error}), error)
  assert.deepEqual(writes, [])
  assert.equal(target.description, '<!-- chrono-harness release -->未完的原文')
  await assert.rejects(run([0, 2], null, null, {...rolling, kind: 'binary'}), /Copier/)
  await assert.rejects(sync(github, {}, {version: 'not-a-version'}), /Expected version/)
})

test('a failed publication owns one issue and its successful retry closes it', async t => {
  const reply = mockRoadmap(t)
  const run = {id: 123, name: 'Release', run_number: 9, run_attempt: 1,
    html_url: 'https://github.com/a/b/actions/runs/123', status: 'completed', head_sha: 'abcdef', conclusion: 'failure'}
  const items = [{number: 1, state: 'open', user: {login: 'somebody'}, body: '<!-- chrono-harness release-run 123 -->'}]
  let hasLabel = false
  const rest = {
    actions: {getWorkflowRun: async ({run_id}) => {assert.equal(run_id, 123); return {data: run}}},
    issues: {
      listForRepo: () => items,
      getLabel: () => {if (!hasLabel) throw Object.assign(new Error('missing label'), {status: 404})},
      createLabel: () => {hasLabel = true},
      create: data => {items.push({...data, number: 2, state: 'open', user: {login: 'github-actions[bot]'}})},
      update: ({issue_number, ...fields}) => {Object.assign(items.find(i => i.number === issue_number), fields)},
    },
  }
  const notify = (action, issue) => {
    const result = {status: run.status, conclusion: run.conclusion}
    reply({operation: 'release-run', ...result}, action !== null)
    if (action !== null) {
      const rows = items.map(({number, state, user, body}) => ({number, state, user, body}))
      reply({operation: 'release-issue', ...result, run_id: 123, issues: rows}, {action, issue})
    }
    return sync.releaseIssue({rest, paginate: async fn => [...fn()]},
      {repo: {owner: 'a', repo: 'b'}, payload: {workflow_run: {id: 123}}})
  }
  await notify('create', null)
  await notify('none', 2)
  assert.equal(items.length, 2)
  assert.equal(hasLabel, true)
  assert.match(items[1].body, /attempts\/1/)
  run.run_attempt = 2
  run.conclusion = 'success'
  await notify('close', 2)
  await notify('none', 2)
  assert.equal(items[1].state, 'closed')
  assert.match(items[1].body, /attempts\/2/)
  assert.equal(items[0].state, 'open')
  run.conclusion = 'failure'
  await notify('reopen', 2)
  assert.equal(items[1].state, 'open')
  run.status = 'in_progress'
  run.conclusion = null
  await notify(null)
})

test('a failed decision aborts before any GitHub write', async t => {
  const reply = mockRoadmap(t)
  reply({operation: 'published', releases: []}, null, new Error('tool exited 2'))
  const github = {rest:{issues:{}, repos:{listReleases: () => []}}, paginate: fn => fn()}
  await assert.rejects(sync(github, {repo:{}, payload:{}}, null), /tool exited 2/)
})
