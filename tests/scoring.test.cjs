const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const html = fs.readFileSync("index.html", "utf8");
const match = html.match(/function calculateExamPercentage\([\s\S]*?\n\}/);
assert.ok(match, "calculateExamPercentage must exist in index.html");
const context = {};
vm.runInNewContext(match[0] + "\nglobalThis.calculateExamPercentage = calculateExamPercentage;", context);
const calculate = context.calculateExamPercentage;

const cases = [
  ["همه صحیح", {correct: 30, wrong: 0, totalQuestions: 30}, 100],
  ["همه غلط", {correct: 0, wrong: 30, totalQuestions: 30}, -33.33],
  ["پاسخ سفید در مخرج می‌ماند", {correct: 6, wrong: 3, totalQuestions: 12}, 41.67],
  ["سؤال حذف‌شده از مخرج و امتیاز خارج است", {correct: 6, wrong: 3, totalQuestions: 12, excludedQuestions: [12]}, 45.45],
  ["تمام سؤال‌ها حذف شده‌اند", {correct: 0, wrong: 0, totalQuestions: 4, excludedQuestions: [1,2,3,4]}, 0],
  ["کف صفر اختیاری", {correct: 0, wrong: 30, totalQuestions: 30, clampMinimumZero: true}, 0],
];
for (const [name, input, expected] of cases) {
  assert.equal(calculate(input), expected, name);
}
assert.throws(() => calculate({correct: 3, wrong: 4, totalQuestions: 5}), /بیشتر/);
assert.throws(() => calculate({correct: 1, wrong: 0, totalQuestions: 5, excludedQuestions: [6]}), /خارج/);
assert.throws(() => calculate({correct: 1, wrong: 0, totalQuestions: 5, negativeCoefficient: 0}), /ضریب/);
console.log(`Passed ${cases.length + 3} negative-marking percentage tests.`);
