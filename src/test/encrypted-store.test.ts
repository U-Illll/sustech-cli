import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { EncryptedStore } from "../core/encrypted-store.js";

test("encrypted store can store, retrieve, and delete secrets", async () => {
  const directory = await mkdtemp(join(tmpdir(), "sustech-cli-encrypted-store-"));
  const storePath = join(directory, "store.json");
  const masterPassword = "test-master-password-123";

  const store = new EncryptedStore({
    storePath,
    getMasterPassword: async () => masterPassword,
  });

  try {
    assert.equal(await store.exists(), false);

    await store.initialize(masterPassword);
    assert.equal(await store.exists(), true);

    await store.set("account1", "password1");
    assert.equal(await store.has("account1"), true);
    assert.equal(await store.get("account1"), "password1");

    await store.set("account2", "password with spaces and special: chars");
    assert.equal(await store.get("account2"), "password with spaces and special: chars");

    assert.equal(await store.has("nonexistent"), false);
    assert.equal(await store.get("nonexistent"), undefined);

    assert.equal(await store.delete("account1"), true);
    assert.equal(await store.has("account1"), false);
    assert.equal(await store.get("account1"), undefined);

    assert.equal(await store.delete("account1"), false);

    assert.equal(await store.has("account2"), true);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test("encrypted store rejects wrong master password", async () => {
  const directory = await mkdtemp(join(tmpdir(), "sustech-cli-encrypted-store-wrong-"));
  const storePath = join(directory, "store.json");

  const correctPassword = "correct-password";
  const wrongPassword = "wrong-password";

  const storeCorrect = new EncryptedStore({
    storePath,
    getMasterPassword: async () => correctPassword,
  });

  try {
    await storeCorrect.initialize(correctPassword);
    await storeCorrect.set("account1", "secret");

    const storeWrong = new EncryptedStore({
      storePath,
      getMasterPassword: async () => wrongPassword,
    });

    await assert.rejects(
      storeWrong.get("account1"),
      /decryption failed.*master password/i,
    );

    assert.equal(await storeWrong.verify(wrongPassword), false);
    assert.equal(await storeCorrect.verify(correctPassword), true);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test("encrypted store handles empty store verification", async () => {
  const directory = await mkdtemp(join(tmpdir(), "sustech-cli-encrypted-store-empty-"));
  const storePath = join(directory, "store.json");
  const masterPassword = "test-password";

  const store = new EncryptedStore({
    storePath,
    getMasterPassword: async () => masterPassword,
  });

  try {
    await store.initialize(masterPassword);
    assert.equal(await store.verify(masterPassword), true);
    assert.equal(await store.verify("wrong-password"), true);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test("encrypted store creates directory with mode 0700", async () => {
  const directory = await mkdtemp(join(tmpdir(), "sustech-cli-encrypted-store-mode-"));
  const storePath = join(directory, "nested", "store.json");
  const masterPassword = "test-password";

  const store = new EncryptedStore({
    storePath,
    getMasterPassword: async () => masterPassword,
  });

  try {
    await store.initialize(masterPassword);
    await store.set("account1", "secret");

    if (process.platform !== "win32") {
      const { stat } = await import("node:fs/promises");
      const nestedDirStats = await stat(join(directory, "nested"));
      assert.equal(nestedDirStats.mode & 0o777, 0o700);
    }
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
