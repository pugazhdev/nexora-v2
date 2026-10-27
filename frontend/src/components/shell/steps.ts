export type StepName = 'Input' | 'Select' | 'Details' | 'Research' | 'Results'

const ORDER: StepName[] = ['Input', 'Select', 'Details', 'Research', 'Results']

/** Select is pointless when only one item is in scope. */
export const stepsFor = (inScopeItems: number): StepName[] =>
  inScopeItems === 1 ? ORDER.filter((s) => s !== 'Select') : ORDER
