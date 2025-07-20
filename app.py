const express = require('express');
const multer = require('multer');
const sharp = require('sharp');
const { v4: uuidv4 } = require('uuid');
const cors = require('cors');
const path = require('path');
const http = require('http');
const { Server } = require('socket.io');
require('dotenv').config();

const app = express();
const server = http.createServer(app);
const io = new Server(server, {
    cors: {
        origin: "*",
        methods: ["GET", "POST"]
    }
});

const PORT = process.env.PORT || 3000;

// OpenAI setup
let openai = null;
try {
    const { OpenAI } = require('openai');
    if (process.env.OPENAI_API_KEY && process.env.OPENAI_API_KEY !== 'your-api-key-here') {
        openai = new OpenAI({
            apiKey: process.env.OPENAI_API_KEY
        });
        console.log('OpenAI initialized successfully');
    }
} catch (error) {
    console.log('OpenAI not available, using demo mode');
}

// Middleware
app.use(cors());
app.use(express.json({ limit: '50mb' }));
app.use(express.static('public'));

const upload = multer({
    storage: multer.memoryStorage(),
    limits: { fileSize: 16 * 1024 * 1024 }
});

// Sessions storage
const sessions = new Map();

// Lighting elements
const LIGHTING_ELEMENTS = {
    "Linear Cove": {
        price_per_foot: 50,
        wattage_per_foot: 4.5,
        lumens_per_foot: 450,
        color: "#00CED1",
        icon: "━━━",
        description: "Continuous LED strip in architectural cove"
    },
    "Pendant": {
        price: 150,
        wattage: 15,
        lumens: 1200,
        color: "#FFD700",
        icon: "⬇◉",
        description: "Suspended decorative light"
    },
    "Ceiling Can": {
        price: 75,
        wattage: 12,
        lumens: 1000,
        color: "#87CEEB",
        icon: "◉",
        description: "Recessed downlight"
    },
    "Wall Sconce": {
        price: 95,
        wattage: 8,
        lumens: 600,
        color: "#FF6347",
        icon: "▣",
        description: "Wall-mounted light"
    },
    "Track Light": {
        price: 85,
        wattage: 12,
        lumens: 900,
        color: "#32CD32",
        icon: "◊",
        description: "Adjustable track spotlight"
    },
    "Step Light": {
        price: 65,
        wattage: 3,
        lumens: 150,
        color: "#FFA500",
        icon: "▢",
        description: "Low-level pathway light"
    },
    "Chandelier": {
        price: 350,
        wattage: 60,
        lumens: 4000,
        color: "#FF69B4",
        icon: "✦",
        description: "Decorative centerpiece"
    }
};

// Upload and AI analysis
app.post('/api/upload', upload.single('floor_plan'), async (req, res) => {
    try {
        const sessionId = req.headers['x-session-id'] || uuidv4();
        
        if (!req.file) {
            return res.status(400).json({ error: 'No file uploaded' });
        }

        // Process image
        const imageBuffer = await sharp(req.file.buffer)
            .resize(1600, 1600, { fit: 'inside', withoutEnlargement: true })
            .png()
            .toBuffer();

        const metadata = await sharp(imageBuffer).metadata();
        const base64 = imageBuffer.toString('base64');

        // AI Analysis
        const analysis = await analyzeFloorPlan(base64, metadata);

        // Store session
        if (!sessions.has(sessionId)) {
            sessions.set(sessionId, {});
        }
        
        sessions.get(sessionId).floorData = {
            image: base64,
            metadata: metadata,
            analysis: analysis,
            designs: {}
        };

        res.json({
            success: true,
            sessionId: sessionId,
            imageWidth: metadata.width,
            imageHeight: metadata.height,
            imageBase64: base64,
            rooms: analysis.rooms,
            summary: analysis.summary
        });

    } catch (error) {
        console.error('Upload error:', error);
        res.status(500).json({ error: error.message });
    }
});

// Generate lighting design for selected room
app.post('/api/generate-design', async (req, res) => {
    try {
        const sessionId = req.headers['x-session-id'];
        const { roomId } = req.body;

        const session = sessions.get(sessionId);
        if (!session || !session.floorData) {
            return res.status(404).json({ error: 'Session not found' });
        }

        const room = session.floorData.analysis.rooms.find(r => r.id === roomId);
        if (!room) {
            return res.status(404).json({ error: 'Room not found' });
        }

        // Generate lighting design
        const design = await generateLightingDesign(room, session.floorData.metadata);
        
        // Store design
        session.floorData.designs[roomId] = design;

        res.json({
            success: true,
            design: design,
            fixtures: design.fixtures,
            reasoning: design.reasoning,
            metrics: design.metrics,
            cost: design.totalCost
        });

    } catch (error) {
        console.error('Design error:', error);
        res.status(500).json({ error: error.message });
    }
});

// Chat endpoint for lighting adjustments
app.post('/api/chat', async (req, res) => {
    try {
        const sessionId = req.headers['x-session-id'];
        const { message, roomId } = req.body;

        const session = sessions.get(sessionId);
        if (!session) {
            return res.status(404).json({ error: 'Session not found' });
        }

        const room = session.floorData.analysis.rooms.find(r => r.id === roomId);
        const currentDesign = session.floorData.designs[roomId];

        const response = await processDesignChat(message, room, currentDesign);

        // If response includes design changes, update the design
        if (response.designUpdate) {
            const updatedDesign = await applyDesignChanges(currentDesign, response.designUpdate, room);
            session.floorData.designs[roomId] = updatedDesign;
            
            res.json({
                success: true,
                message: response.message,
                designUpdate: updatedDesign,
                fixtures: updatedDesign.fixtures
            });
        } else {
            res.json({
                success: true,
                message: response.message
            });
        }

    } catch (error) {
        console.error('Chat error:', error);
        res.status(500).json({ error: error.message });
    }
});

// AI Analysis function
async function analyzeFloorPlan(imageBase64, metadata) {
    if (!openai) {
        return getDemoAnalysis(metadata);
    }

    try {
        const prompt = `Analyze this floor plan image and identify all rooms with their boundaries, furniture, and features.

For each room provide:
1. Room type and name
2. Boundary coordinates [x1, y1, x2, y2] in pixels
3. Dimensions and area
4. All furniture and objects inside with their positions
5. Doors and windows

Return a detailed JSON with all rooms and their contents.`;

        const response = await openai.chat.completions.create({
            model: "gpt-4-vision-preview",
            messages: [{
                role: "user",
                content: [
                    { type: "text", text: prompt },
                    { type: "image_url", image_url: { url: `data:image/png;base64,${imageBase64}` } }
                ]
            }],
            max_tokens: 4000
        });

        const content = response.choices[0].message.content;
        const jsonMatch = content.match(/\{[\s\S]*\}/);
        if (jsonMatch) {
            const analysis = JSON.parse(jsonMatch[0]);
            // Add IDs if missing
            analysis.rooms = analysis.rooms.map((room, index) => ({
                id: room.id || `room_${index + 1}`,
                ...room
            }));
            return analysis;
        }
    } catch (error) {
        console.error('AI analysis error:', error);
    }

    return getDemoAnalysis(metadata);
}

// Demo analysis for testing
function getDemoAnalysis(metadata) {
    const width = metadata.width || 1600;
    const height = metadata.height || 1200;
    
    return {
        summary: {
            total_rooms: 6,
            building_type: "residential",
            total_area: "2,100 sq ft"
        },
        rooms: [
            {
                id: "room_1",
                name: "Kitchen",
                type: "kitchen",
                boundary: [50, 50, 550, 450],
                dimensions: "20x16 ft",
                area: "320 sq ft",
                objects: [
                    { type: "kitchen_island", position: [300, 250], dimensions: "8x4 ft" },
                    { type: "refrigerator", position: [100, 100], dimensions: "3x2.5 ft" },
                    { type: "stove", position: [200, 100], dimensions: "2.5x2 ft" },
                    { type: "sink", position: [350, 100], dimensions: "3x2 ft" }
                ],
                features: [
                    { type: "window", position: [300, 50], width: 60 },
                    { type: "door", position: [550, 250], width: 36 }
                ]
            },
            {
                id: "room_2",
                name: "Living Room",
                type: "living",
                boundary: [600, 50, 1100, 500],
                dimensions: "20x18 ft",
                area: "360 sq ft",
                objects: [
                    { type: "sofa", position: [850, 300], dimensions: "8x3 ft" },
                    { type: "coffee_table", position: [850, 200], dimensions: "4x2 ft" },
                    { type: "tv_stand", position: [850, 100], dimensions: "5x1.5 ft" },
                    { type: "armchair", position: [700, 300], dimensions: "3x3 ft" }
                ],
                features: [
                    { type: "window", position: [850, 50], width: 100 },
                    { type: "door", position: [600, 275], width: 36 }
                ]
            },
            {
                id: "room_3",
                name: "Master Bedroom",
                type: "bedroom",
                boundary: [50, 500, 450, 850],
                dimensions: "16x14 ft",
                area: "224 sq ft",
                objects: [
                    { type: "bed", position: [250, 675], dimensions: "6x7 ft" },
                    { type: "nightstand", position: [150, 675], dimensions: "2x2 ft" },
                    { type: "nightstand", position: [350, 675], dimensions: "2x2 ft" },
                    { type: "dresser", position: [250, 800], dimensions: "5x2 ft" }
                ],
                features: [
                    { type: "window", position: [250, 500], width: 48 },
                    { type: "door", position: [450, 675], width: 32 }
                ]
            },
            {
                id: "room_4",
                name: "Bathroom",
                type: "bathroom",
                boundary: [500, 500, 750, 700],
                dimensions: "10x8 ft",
                area: "80 sq ft",
                objects: [
                    { type: "vanity", position: [625, 550], dimensions: "4x2 ft" },
                    { type: "toilet", position: [575, 650], dimensions: "2x2.5 ft" },
                    { type: "shower", position: [700, 625], dimensions: "3x3 ft" }
                ],
                features: [
                    { type: "door", position: [500, 600], width: 28 }
                ]
            },
            {
                id: "room_5",
                name: "Study",
                type: "office",
                boundary: [800, 600, 1100, 850],
                dimensions: "12x10 ft",
                area: "120 sq ft",
                objects: [
                    { type: "desk", position: [950, 725], dimensions: "5x2.5 ft" },
                    { type: "office_chair", position: [950, 750], dimensions: "2x2 ft" },
                    { type: "bookshelf", position: [850, 725], dimensions: "3x1 ft" }
                ],
                features: [
                    { type: "window", position: [950, 600], width: 36 },
                    { type: "door", position: [800, 725], width: 32 }
                ]
            },
            {
                id: "room_6",
                name: "Dining Room",
                type: "dining",
                boundary: [1150, 200, 1550, 500],
                dimensions: "16x12 ft",
                area: "192 sq ft",
                objects: [
                    { type: "dining_table", position: [1350, 350], dimensions: "6x4 ft" },
                    { type: "dining_chair", position: [1300, 350], dimensions: "1.5x1.5 ft" },
                    { type: "dining_chair", position: [1400, 350], dimensions: "1.5x1.5 ft" },
                    { type: "cabinet", position: [1350, 450], dimensions: "5x2 ft" }
                ],
                features: [
                    { type: "window", position: [1350, 200], width: 60 },
                    { type: "door", position: [1150, 350], width: 36 }
                ]
            }
        ]
    };
}

// Generate lighting design with reasoning
async function generateLightingDesign(room, metadata) {
    const pixelsPerFoot = 25; // Approximate scale
    const design = {
        roomId: room.id,
        roomName: room.name,
        roomType: room.type,
        fixtures: [],
        reasoning: {},
        metrics: {},
        totalCost: 0
    };

    // Room-specific lighting logic with reasoning
    switch (room.type) {
        case 'kitchen':
            design.reasoning.overall = "Kitchen requires layered lighting: task lighting for work areas, ambient for general illumination";
            
            // Island pendant lighting
            const island = room.objects.find(o => o.type === 'kitchen_island');
            if (island) {
                const pendantCount = Math.ceil(parseFloat(island.dimensions) / 3);
                const spacing = 100; // pixels
                
                for (let i = 0; i < pendantCount; i++) {
                    design.fixtures.push({
                        id: `pendant_${i}`,
                        type: "Pendant",
                        position: {
                            x: island.position[0] - (pendantCount - 1) * spacing / 2 + i * spacing,
                            y: island.position[1]
                        },
                        purpose: "Task lighting for island work surface",
                        height: "30 inches above counter"
                    });
                }
                design.reasoning.pendants = `${pendantCount} pendants spaced evenly over the ${island.dimensions} island for optimal task lighting`;
            }

            // Under cabinet lighting
            design.fixtures.push({
                id: "undercab_1",
                type: "Linear Cove",
                position: { x: room.boundary[0] + 100, y: room.boundary[1] + 50 },
                length: 10,
                purpose: "Under-cabinet task lighting",
                placement: "Under upper cabinets"
            });

            // Can lights for general illumination
            const kitchenCans = calculateGridLighting(room.boundary, 100);
            kitchenCans.forEach((pos, i) => {
                design.fixtures.push({
                    id: `can_${i}`,
                    type: "Ceiling Can",
                    position: pos,
                    purpose: "General ambient lighting"
                });
            });
            design.reasoning.cans = `${kitchenCans.length} can lights in grid pattern for even ambient lighting`;
            break;

        case 'living':
            design.reasoning.overall = "Living room needs flexible lighting: ambient for general use, accent for artwork, task for reading";
            
            // Perimeter cove lighting
            design.fixtures.push({
                id: "cove_perimeter",
                type: "Linear Cove",
                position: { x: room.boundary[0] + 50, y: room.boundary[1] + 20 },
                length: calculatePerimeter(room.boundary) / pixelsPerFoot,
                purpose: "Indirect ambient lighting",
                placement: "Perimeter cove"
            });
            design.reasoning.cove = "Perimeter cove provides soft, indirect lighting without glare";

            // Track lights for artwork
            const trackCount = 3;
            for (let i = 0; i < trackCount; i++) {
                design.fixtures.push({
                    id: `track_${i}`,
                    type: "Track Light",
                    position: {
                        x: room.boundary[0] + (room.boundary[2] - room.boundary[0]) / (trackCount + 1) * (i + 1),
                        y: room.boundary[1] + 80
                    },
                    purpose: "Accent lighting for artwork",
                    aimAngle: 30
                });
            }
            design.reasoning.track = "Track lights positioned to highlight artwork and create visual interest";
            break;

        case 'bedroom':
            design.reasoning.overall = "Bedroom lighting should be restful: soft ambient light with task lighting for reading";
            
            // Cove lighting avoiding bed wall
            const bed = room.objects.find(o => o.type === 'bed');
            design.fixtures.push({
                id: "cove_ambient",
                type: "Linear Cove",
                position: { x: room.boundary[0] + 50, y: room.boundary[1] + 20 },
                length: 20,
                purpose: "Soft ambient lighting",
                placement: "Three walls, avoiding headboard"
            });

            // Bedside sconces
            if (bed) {
                design.fixtures.push(
                    {
                        id: "sconce_left",
                        type: "Wall Sconce",
                        position: { x: bed.position[0] - 100, y: bed.position[1] - 50 },
                        purpose: "Reading light left side",
                        mounting: "60 inches from floor"
                    },
                    {
                        id: "sconce_right",
                        type: "Wall Sconce",
                        position: { x: bed.position[0] + 100, y: bed.position[1] - 50 },
                        purpose: "Reading light right side",
                        mounting: "60 inches from floor"
                    }
                );
                design.reasoning.sconces = "Wall sconces provide adjustable task lighting without table clutter";
            }

            // Step lights
            design.fixtures.push(
                {
                    id: "step_1",
                    type: "Step Light",
                    position: { x: bed.position[0] - 80, y: bed.position[1] + 80 },
                    purpose: "Night navigation"
                },
                {
                    id: "step_2",
                    type: "Step Light",
                    position: { x: bed.position[0] + 80, y: bed.position[1] + 80 },
                    purpose: "Night navigation"
                }
            );
            design.reasoning.stepLights = "Step lights provide safe nighttime navigation without disturbing sleep";
            break;

        case 'bathroom':
            design.reasoning.overall = "Bathroom needs bright, even lighting for grooming tasks plus ambient lighting";
            
            const vanity = room.objects.find(o => o.type === 'vanity');
            if (vanity) {
                design.fixtures.push({
                    id: "vanity_light",
                    type: "Linear Cove",
                    position: { x: vanity.position[0], y: vanity.position[1] - 40 },
                    length: 4,
                    purpose: "Task lighting for grooming",
                    placement: "Above mirror"
                });
                design.reasoning.vanity = "Linear LED above mirror provides even, shadow-free lighting for grooming";
            }

            // Shower light
            const shower = room.objects.find(o => o.type === 'shower');
            if (shower) {
                design.fixtures.push({
                    id: "shower_can",
                    type: "Ceiling Can",
                    position: { x: shower.position[0], y: shower.position[1] },
                    purpose: "Shower task lighting",
                    rating: "Wet location rated"
                });
            }

            // General lighting
            design.fixtures.push({
                id: "bath_can",
                type: "Ceiling Can",
                position: { 
                    x: (room.boundary[0] + room.boundary[2]) / 2,
                    y: (room.boundary[1] + room.boundary[3]) / 2
                },
                purpose: "General ambient lighting"
            });
            break;

        case 'office':
        case 'study':
            design.reasoning.overall = "Office lighting optimized for productivity: bright task lighting with minimal glare";
            
            const desk = room.objects.find(o => o.type === 'desk');
            if (desk) {
                design.fixtures.push({
                    id: "desk_pendant",
                    type: "Pendant",
                    position: { x: desk.position[0], y: desk.position[1] },
                    purpose: "Primary task lighting",
                    height: "30 inches above desk"
                });
                design.reasoning.desk = "Pendant over desk provides focused task lighting for work";
            }

            // Ambient lighting
            design.fixtures.push({
                id: "office_cove",
                type: "Linear Cove",
                position: { x: room.boundary[0] + 50, y: room.boundary[1] + 20 },
                length: 15,
                purpose: "Indirect ambient lighting",
                placement: "North and west walls"
            });
            
            // Bookshelf accent
            const bookshelf = room.objects.find(o => o.type === 'bookshelf');
            if (bookshelf) {
                design.fixtures.push({
                    id: "shelf_track",
                    type: "Track Light",
                    position: { x: bookshelf.position[0], y: bookshelf.position[1] - 100 },
                    purpose: "Accent lighting for books",
                    aimAngle: 45
                });
            }
            break;

        case 'dining':
            design.reasoning.overall = "Dining room centers on statement lighting with ambient support";
            
            const table = room.objects.find(o => o.type === 'dining_table');
            if (table) {
                design.fixtures.push({
                    id: "chandelier",
                    type: "Chandelier",
                    position: { x: table.position[0], y: table.position[1] },
                    purpose: "Statement lighting and task illumination",
                    height: "30-36 inches above table"
                });
                design.reasoning.chandelier = "Chandelier provides both decorative appeal and functional dining light";
            }

            // Wall sconces for ambiance
            design.fixtures.push(
                {
                    id: "dining_sconce_1",
                    type: "Wall Sconce",
                    position: { x: room.boundary[0] + 50, y: (room.boundary[1] + room.boundary[3]) / 2 },
                    purpose: "Ambient accent lighting"
                },
                {
                    id: "dining_sconce_2",
                    type: "Wall Sconce",
                    position: { x: room.boundary[2] - 50, y: (room.boundary[1] + room.boundary[3]) / 2 },
                    purpose: "Ambient accent lighting"
                }
            );
            design.reasoning.sconces = "Wall sconces add layered lighting and create intimate dining atmosphere";
            break;
    }

    // Calculate metrics
    design.metrics = calculateLightingMetrics(design.fixtures, room.area);
    design.totalCost = calculateTotalCost(design.fixtures);

    return design;
}

// Calculate grid positions for can lights
function calculateGridLighting(boundary, spacing) {
    const positions = [];
    const [x1, y1, x2, y2] = boundary;
    const width = x2 - x1;
    const height = y2 - y1;
    
    const cols = Math.floor(width / spacing);
    const rows = Math.floor(height / spacing);
    
    const xOffset = (width - (cols - 1) * spacing) / 2;
    const yOffset = (height - (rows - 1) * spacing) / 2;
    
    for (let i = 0; i < rows; i++) {
        for (let j = 0; j < cols; j++) {
            positions.push({
                x: x1 + xOffset + j * spacing,
                y: y1 + yOffset + i * spacing
            });
        }
    }
    
    return positions;
}

// Calculate room perimeter
function calculatePerimeter(boundary) {
    const [x1, y1, x2, y2] = boundary;
    return 2 * ((x2 - x1) + (y2 - y1));
}

// Calculate lighting metrics
function calculateLightingMetrics(fixtures, roomArea) {
    let totalWatts = 0;
    let totalLumens = 0;
    
    fixtures.forEach(fixture => {
        const element = LIGHTING_ELEMENTS[fixture.type];
        if (element) {
            if (fixture.type === "Linear Cove") {
                const length = fixture.length || 10;
                totalWatts += length * element.wattage_per_foot;
                totalLumens += length * element.lumens_per_foot;
            } else {
                totalWatts += element.wattage || 0;
                totalLumens += element.lumens || 0;
            }
        }
    });
    
    const areaSqft = parseFloat(roomArea) || 100;
    
    return {
        totalWatts: totalWatts.toFixed(1),
        totalLumens: Math.round(totalLumens),
        wattsPerSqFt: (totalWatts / areaSqft).toFixed(2),
        lumensPerSqFt: Math.round(totalLumens / areaSqft),
        meetsEnergyCode: (totalWatts / areaSqft) <= 1.2
    };
}

// Calculate total cost
function calculateTotalCost(fixtures) {
    let cost = 0;
    
    fixtures.forEach(fixture => {
        const element = LIGHTING_ELEMENTS[fixture.type];
        if (element) {
            if (fixture.type === "Linear Cove") {
                const length = fixture.length || 10;
                cost += length * element.price_per_foot;
            } else {
                cost += element.price || 0;
            }
        }
    });
    
    return Math.round(cost);
}

// Process design chat
async function processDesignChat(message, room, currentDesign) {
    const lowerMessage = message.toLowerCase();
    
    // Check for specific change requests
    if (lowerMessage.includes('add') || lowerMessage.includes('more')) {
        if (lowerMessage.includes('pendant')) {
            return {
                message: "I'll add another pendant light for better task coverage.",
                designUpdate: { action: 'add', fixtureType: 'Pendant' }
            };
        } else if (lowerMessage.includes('can') || lowerMessage.includes('recessed')) {
            return {
                message: "Adding more recessed lights for improved general illumination.",
                designUpdate: { action: 'add', fixtureType: 'Ceiling Can' }
            };
        }
    }
    
    if (lowerMessage.includes('remove') || lowerMessage.includes('less')) {
        return {
            message: "I'll remove some fixtures to reduce the lighting intensity.",
            designUpdate: { action: 'remove' }
        };
    }
    
    if (lowerMessage.includes('why')) {
        return {
            message: explainDesignReasoning(room, currentDesign)
        };
    }
    
    if (lowerMessage.includes('cost') || lowerMessage.includes('price')) {
        return {
            message: `The current design costs $${currentDesign.totalCost}. ${getCostBreakdown(currentDesign.fixtures)}`
        };
    }
    
    if (lowerMessage.includes('energy') || lowerMessage.includes('efficiency')) {
        const metrics = currentDesign.metrics;
        return {
            message: `Energy usage: ${metrics.totalWatts}W total, ${metrics.wattsPerSqFt}W per sq.ft. ${metrics.meetsEnergyCode ? '✓ Meets energy code requirements.' : '⚠️ Exceeds energy code limit of 1.2W/sq.ft.'}`
        };
    }
    
    // Default response
    return {
        message: "I can help you adjust the lighting design. You can ask me to add or remove fixtures, explain the design choices, or check energy efficiency."
    };
}

// Explain design reasoning
function explainDesignReasoning(room, design) {
    let explanation = `For this ${room.type}, I designed the lighting based on these principles:\n\n`;
    
    explanation += design.reasoning.overall + "\n\n";
    
    // Explain each fixture type
    const fixtureTypes = [...new Set(design.fixtures.map(f => f.type))];
    fixtureTypes.forEach(type => {
        const fixtures = design.fixtures.filter(f => f.type === type);
        const element = LIGHTING_ELEMENTS[type];
        explanation += `**${type}** (${fixtures.length}x): ${element.description}\n`;
        
        if (design.reasoning[type.toLowerCase()]) {
            explanation += `- ${design.reasoning[type.toLowerCase()]}\n`;
        }
        
        fixtures.forEach(f => {
            if (f.purpose) {
                explanation += `- ${f.purpose}\n`;
            }
        });
        explanation += "\n";
    });
    
    return explanation;
}

// Get cost breakdown
function getCostBreakdown(fixtures) {
    const breakdown = {};
    let total = 0;
    
    fixtures.forEach(fixture => {
        const element = LIGHTING_ELEMENTS[fixture.type];
        if (element) {
            if (!breakdown[fixture.type]) {
                breakdown[fixture.type] = { count: 0, cost: 0 };
            }
            
            if (fixture.type === "Linear Cove") {
                const length = fixture.length || 10;
                breakdown[fixture.type].count += length;
                breakdown[fixture.type].cost += length * element.price_per_foot;
            } else {
                breakdown[fixture.type].count += 1;
                breakdown[fixture.type].cost += element.price || 0;
            }
        }
    });
    
    let message = "Breakdown: ";
    Object.entries(breakdown).forEach(([type, data]) => {
        message += `${type}: $${Math.round(data.cost)}, `;
        total += data.cost;
    });
    
    return message;
}

// Apply design changes from chat
async function applyDesignChanges(currentDesign, changes, room) {
    const updatedDesign = JSON.parse(JSON.stringify(currentDesign)); // Deep copy
    
    if (changes.action === 'add' && changes.fixtureType) {
        // Add fixture based on type and room
        const newFixture = {
            id: `${changes.fixtureType.toLowerCase()}_${Date.now()}`,
            type: changes.fixtureType,
            position: findOptimalPosition(room, changes.fixtureType, currentDesign.fixtures),
            purpose: `Additional ${changes.fixtureType} added per request`
        };
        
        updatedDesign.fixtures.push(newFixture);
        updatedDesign.reasoning[`userAdded${Date.now()}`] = `Added ${changes.fixtureType} based on user preference for more lighting`;
    }
    
    if (changes.action === 'remove') {
        // Remove last fixture of most numerous type
        const typeCounts = {};
        updatedDesign.fixtures.forEach(f => {
            typeCounts[f.type] = (typeCounts[f.type] || 0) + 1;
        });
        
        const mostCommonType = Object.entries(typeCounts).sort((a, b) => b[1] - a[1])[0][0];
        const indexToRemove = updatedDesign.fixtures.map((f, i) => f.type === mostCommonType ? i : -1).filter(i => i >= 0).pop();
        
        if (indexToRemove >= 0) {
            updatedDesign.fixtures.splice(indexToRemove, 1);
            updatedDesign.reasoning[`userRemoved${Date.now()}`] = `Removed ${mostCommonType} to reduce lighting intensity per user request`;
        }
    }
    
    // Recalculate metrics and cost
    updatedDesign.metrics = calculateLightingMetrics(updatedDesign.fixtures, room.area);
    updatedDesign.totalCost = calculateTotalCost(updatedDesign.fixtures);
    
    return updatedDesign;
}

// Find optimal position for new fixture
function findOptimalPosition(room, fixtureType, existingFixtures) {
    const [x1, y1, x2, y2] = room.boundary;
    const centerX = (x1 + x2) / 2;
    const centerY = (y1 + y2) / 2;
    
    // Find a position that doesn't overlap with existing fixtures
    let position = { x: centerX, y: centerY };
    let offset = 50;
    let found = false;
    
    while (!found && offset < 200) {
        found = true;
        for (let fixture of existingFixtures) {
            const dist = Math.sqrt(
                Math.pow(position.x - fixture.position.x, 2) + 
                Math.pow(position.y - fixture.position.y, 2)
            );
            if (dist < 50) {
                found = false;
                position.x += offset;
                if (position.x > x2 - 50) {
                    position.x = x1 + 50;
                    position.y += offset;
                }
                break;
            }
        }
        offset += 10;
    }
    
    return position;
}

// Socket.io for real-time updates
io.on('connection', (socket) => {
    console.log('Client connected:', socket.id);
    
    socket.on('join-session', (sessionId) => {
        socket.join(sessionId);
    });
    
    socket.on('design-update', (data) => {
        socket.to(data.sessionId).emit('design-updated', data);
    });
    
    socket.on('disconnect', () => {
        console.log('Client disconnected:', socket.id);
    });
});

// Start server
server.listen(PORT, () => {
    console.log(`
╔════════════════════════════════════════════════════════════════╗
║     Ensemble Lighting Designer Pro - AI Powered                ║
║                                                                ║
║     Server running at: http://localhost:${PORT}                    ║
║     Status: ${openai ? '✓ AI Connected' : '⚠ Demo Mode'}                                  ║
║                                                                ║
║     Features:                                                  ║
║     • AI room detection with object analysis                  ║
║     • Click to select rooms from image                        ║
║     • Automatic fixture placement with reasoning              ║
║     • Interactive chat for design adjustments                 ║
║                                                                ║
╚════════════════════════════════════════════════════════════════╝
    `);
});