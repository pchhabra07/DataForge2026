export interface PracticeSentence {
  id: number;
  text: string;
  difficulty: string;
  category: string;
}

export const SENTENCES: PracticeSentence[] = [
  { id: 1, text: "The quick brown fox jumps over the lazy dog.", difficulty: "easy", category: "general" },
  { id: 2, text: "Good morning, my name is Alex and I am happy to be here.", difficulty: "easy", category: "general" },
  { id: 3, text: "Please remember to bring your notebook to the meeting.", difficulty: "easy", category: "general" },
  { id: 4, text: "The university library is an excellent resource for international students.", difficulty: "medium", category: "general" },
  { id: 5, text: "Communication skills are particularly important for professional development.", difficulty: "medium", category: "general" },
  { id: 6, text: "The temperature has been fluctuating considerably throughout the week.", difficulty: "medium", category: "general" },
  { id: 7, text: "The pharmaceutical company developed an extraordinarily effective vaccine.", difficulty: "hard", category: "technical" },
  { id: 8, text: "Statistical analysis revealed a significant correlation between the variables.", difficulty: "hard", category: "technical" },
  { id: 9, text: "She sells seashells by the seashore, and the shells she sells are seashells.", difficulty: "hard", category: "tongue-twister" },
  { id: 10, text: "The entrepreneur's innovative algorithm revolutionized the manufacturing process.", difficulty: "hard", category: "technical" },
];

export const FIRST_SENTENCE: PracticeSentence = SENTENCES[0];
