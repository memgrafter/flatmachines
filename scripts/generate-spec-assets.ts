#!/usr/bin/env npx tsx
/**
 * Generate spec assets for SDK packages.
 *
 * Creates:
 * - flatagent.d.ts / flatmachine.d.ts (full specs)
 * - flatagent.slim.d.ts / flatmachine.slim.d.ts (no comments, for LLM/machine reading)
 * - flatagent.schema.json / flatmachine.schema.json (JSON schema for validation)
 *
 * Usage:
 *   npx tsx scripts/generate-spec-assets.ts [target-dir]
 *
 * Dependencies:
 *   npm install tsx typescript ts-json-schema-generator
 */

import * as fs from "fs";
import * as path from "path";
import { fileURLToPath } from "url";
import * as ts from "typescript";
import { createGenerator } from "ts-json-schema-generator";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..");

interface SpecConfig {
  filename: string;
  rootType: string;
}

const SPECS: SpecConfig[] = [
  { filename: "flatagent.d.ts", rootType: "AgentWrapper" },
  { filename: "flatmachine.d.ts", rootType: "MachineWrapper" },
  { filename: "profiles.d.ts", rootType: "ProfilesWrapper" },
  { filename: "flatagents-runtime.d.ts", rootType: "SDKRuntimeWrapper" },
];

/**
 * Use TypeScript compiler to emit d.ts without comments.
 */
function emitWithoutComments(srcPath: string): string {
  const content = fs.readFileSync(srcPath, "utf-8");

  // Parse the source file
  const sourceFile = ts.createSourceFile(
    path.basename(srcPath),
    content,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TS
  );

  // Create a printer that removes comments
  const printer = ts.createPrinter({
    removeComments: true,
    newLine: ts.NewLineKind.LineFeed,
  });

  return printer.printFile(sourceFile);
}

/**
 * Generate JSON Schema from TypeScript using ts-json-schema-generator.
 */
function generateJsonSchema(srcPath: string, rootType: string): object {
  const config = {
    path: srcPath,
    tsconfig: undefined,
    type: rootType,
    skipTypeCheck: true,
  };

  const generator = createGenerator(config);
  return generator.createSchema(rootType);
}

/**
 * Generate all spec assets for a target directory.
 */
function generateAssets(targetDir: string): void {
  // Ensure target directory exists
  if (!fs.existsSync(targetDir)) {
    fs.mkdirSync(targetDir, { recursive: true });
  }

  for (const spec of SPECS) {
    const srcPath = path.join(REPO_ROOT, spec.filename);

    if (!fs.existsSync(srcPath)) {
      console.error(`ERROR: ${srcPath} not found`);
      process.exit(1);
    }

    const content = fs.readFileSync(srcPath, "utf-8");

    // Write full spec
    const fullDest = path.join(targetDir, spec.filename);
    fs.writeFileSync(fullDest, content);
    console.log(`Created: ${fullDest}`);

    // Write slim spec (no comments) using TS compiler
    const slimContent = emitWithoutComments(srcPath);
    const slimName = spec.filename.replace(".d.ts", ".slim.d.ts");
    const slimDest = path.join(targetDir, slimName);
    fs.writeFileSync(slimDest, slimContent);
    console.log(`Created: ${slimDest}`);

    // Write JSON schema using ts-json-schema-generator
    const jsonSchema = generateJsonSchema(srcPath, spec.rootType);
    const jsonName = spec.filename.replace(".d.ts", ".schema.json");
    const jsonDest = path.join(targetDir, jsonName);
    fs.writeFileSync(jsonDest, JSON.stringify(jsonSchema, null, 2) + "\n");
    console.log(`Created: ${jsonDest}`);
  }
}

/**
 * Extract SPEC_VERSION constant from a TypeScript spec file using AST.
 */
function extractSpecVersion(specPath: string): string {
  const content = fs.readFileSync(specPath, "utf-8");

  // Parse the source file
  const sourceFile = ts.createSourceFile(
    path.basename(specPath),
    content,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TS
  );

  // Find SPEC_VERSION export
  let version: string | undefined;

  function visit(node: ts.Node) {
    // Look for: export const SPEC_VERSION = "0.6.0"
    if (ts.isVariableStatement(node)) {
      const exportModifier = node.modifiers?.find(
        m => m.kind === ts.SyntaxKind.ExportKeyword
      );

      if (exportModifier) {
        node.declarationList.declarations.forEach(decl => {
          if (ts.isIdentifier(decl.name) && decl.name.text === "SPEC_VERSION") {
            if (decl.initializer && ts.isStringLiteral(decl.initializer)) {
              version = decl.initializer.text;
            }
          }
        });
      }
    }

    ts.forEachChild(node, visit);
  }

  visit(sourceFile);

  if (!version) {
    throw new Error(`Could not find SPEC_VERSION constant in ${specPath}`);
  }

  return version;
}

// Main execution
const args = process.argv.slice(2);

// Handle --extract-version flag for use by lint scripts
if (args[0] === "--extract-version" && args[1]) {
  const specPath = path.resolve(args[1]);
  try {
    const version = extractSpecVersion(specPath);
    console.log(version);
    process.exit(0);
  } catch (error) {
    console.error(`Error: ${error instanceof Error ? error.message : String(error)}`);
    process.exit(1);
  }
}

// Normal asset generation - default targets
const targetDirs = args.length > 0 ? args : [
  path.join(REPO_ROOT, "assets"),
  path.join(REPO_ROOT, "sdk", "python", "flatagents", "flatagents", "assets"),
  path.join(REPO_ROOT, "sdk", "python", "flatmachines", "flatmachines", "assets"),
  path.join(REPO_ROOT, "sdk", "js", "packages", "flatagents", "schemas"),
  path.join(REPO_ROOT, "sdk", "js", "packages", "flatmachines", "schemas"),
];

for (const targetDir of targetDirs) {
  console.log(`Generating spec assets to: ${targetDir}\n`);
  generateAssets(targetDir);
  console.log("");
}

console.log("Done!");

