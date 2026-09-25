# CareSync AI — Dataset-Driven Multi-Agent Healthcare Operations Platform

CareSync AI is an AI-powered hospital operations platform. It strictly enforces a **Zero Preloaded Data Policy**, starting completely empty with zero hardcoded numbers or fake patients. The application becomes live **only after** a user uploads a hospital operational dataset (CSV, Excel XLSX/XLS, or JSON).

---

## Key Architecture Principles

1. **Zero Preloaded Hospital Data**:
   - Dashboards, KPIs (`—`), charts, and tables remain empty until a dataset is uploaded.
   - Agents display `● Waiting for Dataset` until operational data is ingested.

2. **Dataset-Driven Operational Intelligence**:
   - Upload single or multiple CSV/XLSX/JSON files or Excel workbooks with multiple sheets (`Patient_Master`, `Visit_Schedule`, `Bed_Inventory`, `Diagnostic_Queue`, `Medicine_Stock`, `Employees`, `Discharge_List`).
   - Uses **Gemini AI** (`GEMINI_API_KEY`) for semantic column mapping (e.g. mapping `Pt_Name` to `name`). Falls back to deterministic rule mapping if Gemini API is absent.

3. **Multi-Agent Engine**:
   - **Hospital Coordinator Agent**: Evaluates hospital emergency load and coordinates priorities.
   - **Bed Management Agent**: Monitors bed capacity, ICU availability, and ward occupancy.
   - **Appointment Agent**: Replaces human approval, reschedules routine appointments during emergency surges, and triggers patient SMS notifications.
   - **Lab Agent**: Identifies lab diagnostic bottlenecks and reroutes pending tests.
   - **Pharmacy Agent**: Scans medicine stock and flags shortage alerts.
   - **Staffing Agent**: Reallocates available clinical staff to emergency triage.
   - **Discharge Agent**: Processes discharge-ready patients and clears bed allocations.

4. **Twilio SMS & Twilio Mock Mode**:
   - Dispatches patient SMS alerts upon appointment rescheduling.
   - If Twilio credentials are absent, automatically enters **Twilio Mock Mode** (`✓ SMS Simulated`) without crashing.

---

## Installation & Setup

1. **Clone & Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Generate Sample Test Dataset** (Optional):
   ```bash
   python create_sample_dataset.py
   ```
   This generates `sample_hospital_data.xlsx` for immediate drag-and-drop testing.

3. **Configure Environment Variables** (Optional):
   Create a `.env` file from `.env.example`:
   ```env
   GEMINI_API_KEY=your_gemini_api_key
   TWILIO_ACCOUNT_SID=your_twilio_sid
   TWILIO_AUTH_TOKEN=your_twilio_token
   TWILIO_PHONE_NUMBER=your_twilio_number
   SECRET_KEY=caresync-super-secret-key-2026
   ```

4. **Run the Application**:
   ```bash
   python app.py
   ```
   Open your browser to: `http://localhost:5000`

---

## Step-by-Step User Flow & Verification

1. **Sign Up / Sign In**:
   - Register a new account or sign in.
2. **Verify Empty State**:
   - Confirm all KPI cards show `—`, charts show `No hospital data available`, and all 7 agents display `● Waiting for Dataset`.
3. **Upload Dataset**:
   - Navigate to **Dataset Management** (`/data`) or click **Upload Hospital Dataset** on the dashboard.
   - Drag & drop `sample_hospital_data.xlsx` or your CSV file.
   - Watch the 6-step progress sequence activate the dataset.
4. **Live Dashboard & Operations**:
   - View populated KPIs, live Plotly charts, and populated module pages (Patients, Appointments, Beds, Labs, Pharmacy, Staffing, Discharge, Reports).
5. **Run Emergency Surge Simulation**:
   - Click **⚡ Run Emergency Surge Simulation** on the dashboard.
   - Watch agents transition from `Waiting` $\rightarrow$ `Running` $\rightarrow$ `Completed`.
   - Observe routine appointments rescheduled, Twilio SMS dispatched, beds freed, and live dashboard metrics updated.
