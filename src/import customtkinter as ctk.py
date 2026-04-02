import customtkinter as ctk
from tkinter import scrolledtext

# Set the theme to match the "Code9" aesthetic
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

class Code9IDE(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Code9 - MLX Local IDE")
        self.geometry("1100x750")

        # Create main grid layout (1 row, 2 columns)
        self.grid_columnconfigure(0, weight=3) # Left side (Editor)
        self.grid_columnconfigure(1, weight=1) # Right side (Chat/Help)
        self.grid_rowconfigure(0, weight=1)

        # --- LEFT PANEL: CODE EDITOR & GENERATOR ---
        self.left_panel = ctk.CTkFrame(self, corner_radius=20, fg_color="#d1e5f4")
        self.left_panel.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
        
        # Title Label inside left panel
        self.label_code9 = ctk.CTkLabel(self.left_panel, text="Code9", font=("Helvetica", 24, "bold"), text_color="#333333")
        self.label_code9.pack(pady=(20, 10))

        # Editor Area (Where user types code)
        self.code_editor = ctk.CTkTextbox(self.left_panel, 
                                          font=("Consolas", 14), 
                                          text_color="#1a1a1a", 
                                          fg_color="transparent",
                                          border_spacing=10)
        self.code_editor.pack(fill="both", expand=True, padx=40, pady=10)
        self.code_editor.insert("0.0", "def singBottlesSong():\n    drink = \"Milk\"\n    # ... (paste code here)")

        # Status / Generating area
        self.status_label = ctk.CTkLabel(self.left_panel, text="Generating...", font=("Helvetica", 12, "italic"), text_color="#555555")
        self.status_label.pack()

        self.info_text = ctk.CTkLabel(self.left_panel, 
                                      text="(generates a shell to run your code without major changes)", 
                                      font=("Helvetica", 16), 
                                      text_color="#1a1a1a")
        self.info_text.pack(pady=(5, 30))

        # --- RIGHT PANEL: CHAT / HELP ---
        self.right_panel = ctk.CTkFrame(self, corner_radius=20, fg_color="#d1e5f4")
        self.right_panel.grid(row=0, column=1, padx=(0, 20), pady=20, sticky="nsew")

        # Chat Bubble Area
        self.help_label = ctk.CTkLabel(self.right_panel, text="how can I help?", font=("Helvetica", 18), text_color="#1a1a1a")
        self.help_label.place(relx=0.5, rely=0.4, anchor="center")

        # Chat Input Area (The bottom bubble in your drawing)
        self.chat_input = ctk.CTkEntry(self.right_panel, 
                                       placeholder_text="...", 
                                       height=50, 
                                       corner_radius=15,
                                       fg_color="#f0f0f0",
                                       text_color="#333333",
                                       border_width=0)
        self.chat_input.pack(side="bottom", fill="x", padx=20, pady=30)

        # Run Button (Floating/Added functionality)
        self.run_button = ctk.CTkButton(self.left_panel, text="Run with MLX", command=self.run_logic, corner_radius=10)
        self.run_button.place(relx=0.95, rely=0.05, anchor="ne")

    def run_logic(self):
        # This is where you will connect your MLX backend later
        print("Sending snippet to MLX model...")
        self.status_label.configure(text="Processing with local model...")

if __name__ == "__main__":
    app = Code9IDE()
    app.mainloop()