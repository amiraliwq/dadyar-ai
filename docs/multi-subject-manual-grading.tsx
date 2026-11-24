import React, { useMemo } from "react";

export type Option = 1 | 2 | 3 | 4;
export type QuestionStatus = "normal" | "excluded" | "double_correct";

export interface ExamSubjectRange {
  id?: string;
  subjectId?: string;
  lessonId?: string | null;
  subjectName: string;
  lessonName?: string;
  startQuestion: number;
  endQuestion: number;
  weight: number;
}

export interface QuestionState {
  question: number;
  status: QuestionStatus;
  acceptedOptions: Option[];
}

export interface SubmissionAnswer {
  submissionId: string;
  answers: Array<Option | null>;
  ocrAnswers: Array<Option | null>;
  questionStates: QuestionState[];
  manualOverride: boolean;
}

export interface SubjectScore {
  subjectName: string;
  lessonName?: string;
  correct: number;
  wrong: number;
  blank: number;
  excluded: number;
  effectiveQuestions: number;
  percentage: number;
  weight: number;
}

export interface ExamScore {
  correct: number;
  wrong: number;
  blank: number;
  excluded: number;
  subjects: SubjectScore[];
  weightedPercentage: number;
}

export function calculateNegativePercentage(
  correct: number,
  wrong: number,
  effectiveQuestions: number,
  coefficient = 3,
  clampAtZero = false,
): number {
  if (![correct, wrong, effectiveQuestions].every(Number.isInteger) ||
      correct < 0 || wrong < 0 || effectiveQuestions < 0 ||
      correct + wrong > effectiveQuestions || coefficient <= 0) {
    throw new RangeError("Invalid scoring inputs");
  }
  if (!effectiveQuestions) return 0;
  const value = 100 * (coefficient * correct - wrong) /
    (coefficient * effectiveQuestions);
  return Number((clampAtZero ? Math.max(0, value) : value).toFixed(2));
}

export function calculateWeightedExamScore(
  answerKey: Option[],
  answers: Array<Option | null>,
  states: QuestionState[],
  ranges: ExamSubjectRange[],
  excludedExamQuestions: number[] = [],
  coefficient = 3,
): ExamScore {
  const stateByQuestion = new Map(states.map(s => [s.question, s]));
  const globallyExcluded = new Set(excludedExamQuestions);
  const sections = [...ranges].sort((a, b) => a.startQuestion - b.startQuestion);
  const source = sections.length ? sections : [{
    subjectName: "کل آزمون",
    startQuestion: 1,
    endQuestion: answerKey.length,
    weight: 1,
  }];
  const summarize = (questions: number[]) => {
    let correct = 0, wrong = 0, blank = 0, excluded = 0;
    for (const q of questions) {
      const state = stateByQuestion.get(q);
      if (globallyExcluded.has(q) || state?.status === "excluded") {
        excluded++;
        continue;
      }
      const answer = answers[q - 1] ?? null;
      if (answer == null) { blank++; continue; }
      const accepted = state?.status === "double_correct"
        ? state.acceptedOptions
        : [answerKey[q - 1]];
      if (accepted.includes(answer)) correct++;
      else wrong++;
    }
    const effectiveQuestions = questions.length - excluded;
    return {
      correct, wrong, blank, excluded, effectiveQuestions,
      percentage: calculateNegativePercentage(correct, wrong, effectiveQuestions, coefficient),
    };
  };
  const subjects = source.map(range => {
    const questions = Array.from(
      { length: range.endQuestion - range.startQuestion + 1 },
      (_, i) => range.startQuestion + i,
    );
    return {
      subjectName: range.subjectName,
      lessonName: range.lessonName,
      weight: range.weight,
      ...summarize(questions),
    };
  });
  const overall = summarize(Array.from({ length: answerKey.length }, (_, i) => i + 1));
  const weightTotal = subjects.reduce((sum, s) => sum + s.weight, 0);
  const weightedPercentage = weightTotal
    ? Number((subjects.reduce((sum, s) => sum + s.percentage * s.weight, 0) / weightTotal).toFixed(2))
    : 0;
  return { ...overall, subjects, weightedPercentage };
}

interface ExamSubjectRangesProps {
  questionCount: number;
  value: ExamSubjectRange[];
  onChange(next: ExamSubjectRange[]): void;
}

export function ExamSubjectRanges({ questionCount, value, onChange }: ExamSubjectRangesProps) {
  const update = (index: number, patch: Partial<ExamSubjectRange>) =>
    onChange(value.map((row, i) => i === index ? { ...row, ...patch } : row));
  const add = () => {
    const next = [...value];
    const last = next[next.length - 1];
    let startQuestion = last ? last.endQuestion + 1 : 1;
    let endQuestion = questionCount;
    if (last && last.endQuestion - last.startQuestion >= 1) {
      const split = Math.floor((last.startQuestion + last.endQuestion) / 2);
      startQuestion = split + 1;
      endQuestion = last.endQuestion;
      next[next.length - 1] = { ...last, endQuestion: split };
    }
    onChange([...next, { subjectName: "", startQuestion, endQuestion, weight: 1 }]);
  };
  return (
    <section dir="rtl" aria-label="تفکیک درس‌های آزمون">
      {value.map((row, index) => (
        <fieldset key={row.id ?? index}>
          <legend>درس {index + 1}</legend>
          <label>نام درس
            <input value={row.subjectName} onChange={e => update(index, { subjectName: e.target.value })} />
          </label>
          <label>مبحث
            <input value={row.lessonName ?? ""} onChange={e => update(index, { lessonName: e.target.value })} />
          </label>
          <label>از سؤال
            <input type="number" min={1} max={questionCount} value={row.startQuestion}
              onChange={e => update(index, { startQuestion: Number(e.target.value) })} />
          </label>
          <label>تا سؤال
            <input type="number" min={1} max={questionCount} value={row.endQuestion}
              onChange={e => update(index, { endQuestion: Number(e.target.value) })} />
          </label>
          <label>ضریب
            <input type="number" min={0.001} step={0.001} value={row.weight}
              onChange={e => update(index, { weight: Number(e.target.value) })} />
          </label>
          <button type="button" onClick={() => onChange(value.filter((_, i) => i !== index))}>
            حذف درس
          </button>
        </fieldset>
      ))}
      <button type="button" onClick={add}>افزودن درس</button>
    </section>
  );
}

interface ManualAnswerGridProps {
  answerKey: Option[];
  answers: Array<Option | null>;
  states: QuestionState[];
  ranges: ExamSubjectRange[];
  excludedExamQuestions?: number[];
  onChange(nextAnswers: Array<Option | null>, nextStates: QuestionState[]): void;
}

export function ManualAnswerGrid({
  answerKey, answers, states, ranges, excludedExamQuestions = [], onChange,
}: ManualAnswerGridProps) {
  const stateByQuestion = new Map(states.map(s => [s.question, s]));
  const score = useMemo(
    () => calculateWeightedExamScore(answerKey, answers, states, ranges, excludedExamQuestions),
    [answerKey, answers, states, ranges, excludedExamQuestions],
  );
  const changeAnswer = (q: number, value: string) => {
    const next = [...answers];
    next[q - 1] = value ? Number(value) as Option : null;
    onChange(next, states);
  };
  const changeStatus = (q: number, status: QuestionStatus) => {
    const current = stateByQuestion.get(q);
    const next = states.filter(s => s.question !== q);
    next.push({
      question: q,
      status,
      acceptedOptions: current?.acceptedOptions ?? [answerKey[q - 1]],
    });
    onChange(answers, next);
  };
  const changeAcceptedOption = (q: number, option: Option, checked: boolean) => {
    const current = stateByQuestion.get(q);
    const accepted = new Set(current?.acceptedOptions ?? [answerKey[q - 1]]);
    checked ? accepted.add(option) : accepted.delete(option);
    const next = states.filter(s => s.question !== q);
    next.push({ question: q, status: "double_correct", acceptedOptions: [...accepted] });
    onChange(answers, next);
  };
  return (
    <section dir="rtl" aria-label="ورود دستی پاسخ‌ها">
      <div aria-live="polite">
        <b>درصد کل وزنی: {score.weightedPercentage.toFixed(2)}٪</b>
        <span> صحیح: {score.correct} · غلط: {score.wrong} · نزده: {score.blank}</span>
        {score.subjects.map(s => (
          <p key={s.subjectName + s.lessonName}>
            {s.subjectName} {s.lessonName ? " / " + s.lessonName : ""}
            : {s.percentage.toFixed(2)}٪ (ضریب {s.weight})
          </p>
        ))}
      </div>
      <div className="manual-answer-grid">
        {answerKey.map((correct, index) => {
          const q = index + 1;
          const state = stateByQuestion.get(q);
          return (
            <fieldset key={q}>
              <legend>سؤال {q} · کلید {correct}</legend>
              <label>پاسخ دانش‌آموز
                <select value={answers[index] ?? ""} onChange={e => changeAnswer(q, e.target.value)}>
                  <option value="">نزده</option>
                  {[1, 2, 3, 4].map(n => <option key={n} value={n}>گزینه {n}</option>)}
                </select>
              </label>
              <label>وضعیت سؤال
                <select value={state?.status ?? "normal"}
                  onChange={e => changeStatus(q, e.target.value as QuestionStatus)}>
                  <option value="normal">عادی</option>
                  <option value="excluded">حذف‌شده</option>
                  <option value="double_correct">دوگزینه‌ای صحیح</option>
                </select>
              </label>
              {state?.status === "double_correct" && (
                <div aria-label={`گزینه‌های صحیح سؤال ${q}`}>
                  {[1, 2, 3, 4].map(n => (
                    <label key={n}>
                      <input type="checkbox" checked={state.acceptedOptions.includes(n as Option)}
                        onChange={e => changeAcceptedOption(q, n as Option, e.target.checked)} />
                      گزینه {n}
                    </label>
                  ))}
                </div>
              )}
            </fieldset>
          );
        })}
      </div>
    </section>
  );
}
