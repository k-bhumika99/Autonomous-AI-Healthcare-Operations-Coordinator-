import os
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

WIDTH = 960
HEIGHT = 540

STATIC_DIR = r"c:\Users\kooki\Desktop\bhoom\static\images"
HERO_PATH = os.path.join(STATIC_DIR, "hero_hospital.jpg")
DOCTOR_PATH = os.path.join(STATIC_DIR, "doctor_patient.jpg")
PHARMACY_PATH = os.path.join(STATIC_DIR, "pharmacy.jpg")
SURGICAL_PATH = os.path.join(STATIC_DIR, "surgical.jpg")

hero_img = Image.open(HERO_PATH).convert("RGB")
doc_img = Image.open(DOCTOR_PATH).convert("RGB")
pharm_img = Image.open(PHARMACY_PATH).convert("RGB")
surg_img = Image.open(SURGICAL_PATH).convert("RGB")

def make_scene(source_img, crop_box, tint_rgb, contrast=1.1, saturation=1.2, mirror=False):
    cropped = source_img.crop(crop_box)
    if mirror:
        cropped = ImageOps.mirror(cropped)
    resized = cropped.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    
    enhanced = ImageEnhance.Contrast(resized).enhance(contrast)
    enhanced = ImageEnhance.Color(enhanced).enhance(saturation)
    enhanced = ImageEnhance.Sharpness(enhanced).enhance(1.2)
    
    tint = Image.new("RGB", (WIDTH, HEIGHT), tint_rgb)
    final_img = Image.blend(enhanced, tint, alpha=0.08)
    return final_img

# 1. Coordinator Agent
img1 = make_scene(hero_img, (0, 0, 1400, 800), (147, 51, 234))
img1.save(os.path.join(STATIC_DIR, "agent_1_coordinator_3d.png"), "PNG")

# 2. Bed Management Agent
img2 = make_scene(doc_img, (800, 100, 1920, 950), (79, 70, 229))
img2.save(os.path.join(STATIC_DIR, "agent_2_bed_management_3d.png"), "PNG")

# 3. Lab Diagnostics Agent
img3 = make_scene(pharm_img, (0, 100, 1100, 850), (225, 29, 72), mirror=True)
img3.save(os.path.join(STATIC_DIR, "agent_3_lab_diagnostics_3d.png"), "PNG")

# 4. Pharmacy Agent
img4 = make_scene(pharm_img, (700, 0, 1920, 800), (217, 119, 6))
img4.save(os.path.join(STATIC_DIR, "agent_4_pharmacy_3d.png"), "PNG")

# 5. Staffing Agent
img5 = make_scene(hero_img, (900, 200, 1920, 950), (13, 148, 136))
img5.save(os.path.join(STATIC_DIR, "agent_5_staffing_3d.png"), "PNG")

# 6. Appointment Agent
img6 = make_scene(doc_img, (0, 0, 1200, 750), (37, 99, 235))
img6.save(os.path.join(STATIC_DIR, "agent_6_appointment_3d.png"), "PNG")

# 7. Discharge Release Agent
img7 = make_scene(doc_img, (300, 100, 1600, 900), (16, 185, 129))
img7.save(os.path.join(STATIC_DIR, "agent_7_discharge_3d.png"), "PNG")

print("Created 7 brand new PNG images with unique filenames!")
