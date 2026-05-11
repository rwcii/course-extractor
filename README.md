# Canvas IMSCC Course Extractor

Extract and browse your Canvas LMS course content from `.imscc` backup files. Built to help teachers recover their lesson data.

## What it does

Takes a Canvas `.imscc` export file and produces an organized, browsable folder you can open in any web browser:

- **Course pages** — lectures, readings, and all wiki content with working images
- **Quizzes** — settings, question banks, correct answers, and point values
- **Assignments** — due dates, point values, grading categories, and descriptions
- **Discussions** — full discussion prompts with formatting preserved
- **Rubrics** — criteria, ratings, and point breakdowns
- **Files** — all images, PDFs, and media extracted and organized
- **Module structure** — the full course layout exactly as it appeared in Canvas

## Requirements

**Python 3.8+** — that's it. No installation, no packages, no dependencies.

Python comes pre-installed on Mac and Linux. Windows users can download it from [python.org](https://www.python.org/downloads/).

## Usage

1. Download `extract.py`
2. Open a terminal and run:

```bash
python3 extract.py your_course_backup.imscc
```

3. Open the `index.html` file in the output folder

That's it. Your course content is now browsable offline.

### Options

```bash
# Specify a custom output folder
python3 extract.py my_course.imscc -o my_output_folder

# The default output folder is named after the input file
python3 extract.py "7402-Applied-Calculus.imscc"
# → creates 7402-Applied-Calculus_extracted/
```

## How to get your .imscc file

If you still have access to Canvas:

1. Go to your course **Settings**
2. Click **Export Course Content**
3. Select **Course** and click **Create Export**
4. Download the `.imscc` file when ready

If you received a backup file from your institution after the incident, it's likely already in `.imscc` format.

## What the output looks like

```
my_course_extracted/
├── index.html          ← Open this in your browser
├── pages/              ← All course pages (lectures, readings, etc.)
├── assessments/        ← Quizzes and question banks with answers
├── discussions/        ← Discussion prompts
├── assignments/        ← (metadata shown in index)
└── files/              ← Images, PDFs, and other media
```

The `index.html` shows your complete course structure with:
- Clickable module navigation matching your Canvas layout
- Assignment details (points, due dates, grading category)
- Color-coded badges for content types (pages, quizzes, discussions, etc.)
- Grading breakdown table
- Rubric details
- File browser organized by type

## Contributing

Issues and pull requests welcome. This is a community tool — if you find edge cases with your course exports, please open an issue.

## License

MIT
