# 🗄️ AV Rack Elevation Generator

A professional tool for generating rack elevation documentation from client proposal CSVs. Upload a CSV with AV equipment and get a beautifully formatted PDF showing the rack layout.

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![Streamlit](https://img.shields.io/badge/Streamlit-1.0+-red.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)

## ✨ Features

- **📤 CSV Upload** - Upload client proposal CSVs in various formats
- **🔍 Auto-Detection** - Automatically detects rack enclosures and sizes from CSV
- **🤖 AI-Powered** - Uses OpenAI GPT-4o to look up product specifications
- **📊 Smart Arrangement** - Intelligently arranges equipment with weight distribution and thermal considerations
- **📄 Professional PDFs** - Generates industry-standard rack elevation diagrams
- **🖥️ Web Interface** - Easy-to-use Streamlit interface with live preview

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- OpenAI API key (for product spec lookups)
- MySQL database (optional, for product catalog)

### Installation

1. Clone the repository:
```bash
git clone https://github.com/YOUR_USERNAME/av-rack-generator.git
cd av-rack-generator
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up environment variables:
```bash
cp .env.example .env
# Edit .env with your API keys
```

4. Run the web interface:
```bash
streamlit run app.py
```

5. Open http://localhost:8501 in your browser

## 📋 CSV Format

The tool supports multiple CSV formats. Here's an example:

```csv
Quantity,Part Number,Cost Price,Sell Price,Phase,LocationPath,System
1,USW-PRO-24-POE,1200,1500,Finish,Equipment Closet,Network & WiFi
1,UDM-PRO-MAX,600,750,Finish,Equipment Closet,Network & WiFi
1,PAV-SIPA125SM-10,2310,3000,Finish,Equipment Closet,Audio
```

## 🛠️ Command Line Usage

You can also use the command-line interface:

```bash
python generate_rack_docs.py path/to/your/proposal.csv \
    --project "Client Project Name" \
    --company "Your Company" \
    --rack-size 42 \
    --page-size tabloid
```

### Options

| Option | Description | Default |
|--------|-------------|---------|
| `--project` | Project name for title block | "AV System" |
| `--company` | Company name for title block | "Your Company" |
| `--rack-size` | Rack size in U (auto-detected if not specified) | 42 |
| `--page-size` | PDF page size: letter, tabloid, arch_c, arch_d | tabloid |
| `--split` | Force split into AV and Network racks | False |

## 📁 Project Structure

```
├── app.py                 # Streamlit web interface
├── generate_rack_docs.py  # Main CLI script
├── csv_parser.py          # CSV parsing and rack detection
├── rack_arranger.py       # Rack layout algorithm
├── pdf_generator.py       # PDF generation with ReportLab
├── openai_client.py       # OpenAI API for product specs
├── db_client.py           # MySQL database client
├── airtable_client.py     # Airtable integration
├── requirements.txt       # Python dependencies
└── README.md
```

## ⚙️ Environment Variables

Create a `.env` file with:

```env
# OpenAI (required for AI product lookups)
OPENAI_API_KEY=your_openai_api_key

# MySQL Database (optional)
MYSQL_HOST=localhost
MYSQL_USER=your_user
MYSQL_PASSWORD=your_password
MYSQL_DATABASE=your_database

# Airtable (optional)
AIRTABLE_API_KEY=your_airtable_key
AIRTABLE_BASE_ID=your_base_id
```

## 📝 License

MIT License - feel free to use this for your AV projects!

## 🤝 Contributing

Contributions welcome! Please feel free to submit a Pull Request.

