import { test } from 'node:test'
import assert from 'node:assert'
import { isEnabled } from './src/flags.mjs'

test('unknown flag is disabled', () => assert.equal(isEnabled('nope', 'prod'), false))
test('cmd-k-search off in prod by default', () => assert.equal(isEnabled('cmd-k-search', 'prod'), false))
